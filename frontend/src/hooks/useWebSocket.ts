import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef } from "react";
import { useMarketStore } from "../store/marketStore";
import { isTauri } from "../utils/tauri";
import { fetchWarmMacdSnapshot } from "../utils/warmMacd";
import type {
  Agent007StateMessage,
  AlertMessage,
  BrokerSnapshotMessage,
  DailyMessage,
  DomSnapshotMessage,
  FlowInversionMessage,
  MacdSignalMessage,
  SyncMessage,
  VolumeProfileMessage,
  TapeIntelligenceMessage,
  TradeMessage,
  WallAddMessage,
  WallRemoveMessage,
  WsBatchMessage,
  WsMessage,
  WsSingleMessage,
  VpOverlayMessage,
} from "../types/messages";

const MAX_BACKOFF_MS = 30000;
/** Intervalo mínimo entre o mesmo alerta (ticker|regra|direção) para evitar spam e duplicidade */
const ALERT_INTERVAL_MS = 60 * 1000;

const lastAlertByKey = new Map<string, number>();

function getAlertCooldownKey(alert: AlertMessage): string {
  return `${alert.ticker}|${alert.rule}|${alert.direction}`;
}
const INITIAL_BACKOFF_MS = 1000;
const WS_CONNECT_TIMEOUT_MS = 10000;
/** Distributor WS. Ver docs/PORTS.md */
const WS_URL_TAURI = "ws://127.0.0.1:8000/ws";
const WS_URL_VP_TAURI = "ws://127.0.0.1:8000/ws/volume-profile";
const WS_URL_TT_TAURI = "ws://127.0.0.1:8000/ws/tape-intelligence";
const TRADE_BATCH_MAX = 200;
const TAURI_MARKET_EVENT = "pq:market-message";
const TAURI_IPC_TRANSPORT_EVENT = "pq:ipc-transport";
const TAURI_IPC_FALLBACK_EVENT = "pq:ipc-fallback";

function getWsUrl(): string {
  if (isTauri()) {
    return WS_URL_TAURI;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${protocol}//${host}/ws`;
}

function getVpWsUrl(): string {
  if (isTauri()) return WS_URL_VP_TAURI;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/volume-profile`;
}

function getTapeWsUrl(): string {
  if (isTauri()) return WS_URL_TT_TAURI;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/tape-intelligence`;
}

function dispatchWsPayload(
  msg: WsSingleMessage,
  store: ReturnType<typeof useMarketStore.getState>,
  opts?: { forceVpTape?: boolean },
): void {
  const forceVpTape = opts?.forceVpTape === true;
  if (
    msg.topic === "system" &&
    (msg as { type?: string }).type === "ipc_fallback"
  ) {
    // Fallback SHM->ZMQ/WebSocket informa troca de transporte, não perda total de conexão.
    store.setWsStatus("connected");
    return;
  }
  if (store.wsStatus !== "connected") {
    store.setWsStatus("connected");
  }
  if (msg.topic === "alert") {
    const a = msg as AlertMessage;
    const key = getAlertCooldownKey(a);
    const now = Date.now();
    const last = lastAlertByKey.get(key);
    if (last != null && now - last < ALERT_INTERVAL_MS) return;
    lastAlertByKey.set(key, now);
    store.addAlert(a);
    return;
  }

  if (msg.topic === "sync") {
    store.updateSync(msg as SyncMessage);
    return;
  }

  if (
    msg.topic === "agent007" &&
    (msg as { type?: string }).type === "state"
  ) {
    store.setAgent007State(msg as Agent007StateMessage);
    return;
  }

  if (msg.topic === "market") {
    const m = msg as { type: string; buy?: unknown[]; sell?: unknown[] };
    if (m.type === "trade") enqueueTrade(msg as TradeMessage);
    else if (m.type === "dom_snapshot")
      enqueueDomSnapshot(msg as DomSnapshotMessage);
    else if (m.type === "wall_add") store.addWall(msg as WallAddMessage);
    else if (m.type === "wall_remove")
      store.removeWall(msg as WallRemoveMessage);
    else if (m.type === "daily") store.updateDaily(msg as DailyMessage);
    else if (m.type === "volume_profile" && (forceVpTape || !vpWsReady))
      {
        const vp = msg as VolumeProfileMessage;
        console.debug(
          `[VP_UI] received symbol=${vp.ticker} total=${vp.total_vol} poc=${vp.poc} vah=${vp.vah} val=${vp.val}`,
        );
        store.updateVolumeProfile(vp);
      }
    else if (m.type === "tape_intelligence" && (forceVpTape || !tapeWsReady))
      store.updateTapeIntelligence(msg as TapeIntelligenceMessage);
    else if (m.type === "vp_overlay")
      store.updateVpOverlay(msg as VpOverlayMessage);
    else if (m.type === "broker_snapshot")
      store.applyBrokerSnapshot(msg as BrokerSnapshotMessage);
    else if (m.type === "flow_inversion")
      store.addFlowInversion(msg as FlowInversionMessage);
    else if (m.type === "macd_signal") {
      store.updateMacd(msg as MacdSignalMessage);
    }
  }
}

function handleMessage(
  data: unknown,
  store: ReturnType<typeof useMarketStore.getState>,
  options?: { dropTrades?: boolean },
): void {
  if (typeof data !== "string") return;
  const dropTrades = options?.dropTrades === true;
  try {
    const msg = JSON.parse(data) as WsMessage;
    if (msg.topic === "ws_batch") {
      const batch = msg as WsBatchMessage;
      for (const item of batch.items) {
        if (
          dropTrades &&
          item.topic === "market" &&
          (item as { type?: string }).type === "trade"
        ) {
          continue;
        }
        dispatchWsPayload(item, store);
      }
      return;
    }
    if (
      dropTrades &&
      msg.topic === "market" &&
      (msg as { type?: string }).type === "trade"
    ) {
      return;
    }
    dispatchWsPayload(msg, store);
  } catch {
    // ignore parse errors
  }
}

/** Singleton compartilhado: uma única conexão WS e ref-count para não fechar no cleanup de um efeito enquanto outro ainda precisa. */
let sharedWs: WebSocket | null = null;
let wsRefCount = 0;
let wsReconnectTimeoutId: ReturnType<typeof setTimeout> | null = null;
let wsBackoffMs = INITIAL_BACKOFF_MS;
let pendingTrades: TradeMessage[] = [];
let tradeFlushTimeoutId: ReturnType<typeof setTimeout> | null = null;
let pendingDomSnapshot: DomSnapshotMessage | null = null;
let domFlushTimeoutId: ReturnType<typeof setTimeout> | null = null;
let ipcTransportMode: "shm" | "websocket" | "unknown" = "unknown";
let tauriUnlistenMarket: (() => void) | null = null;
let tauriUnlistenTransport: (() => void) | null = null;
let tauriUnlistenFallback: (() => void) | null = null;
let sharedVpWs: WebSocket | null = null;
let sharedTapeWs: WebSocket | null = null;
let vpWsRefCount = 0;
let tapeWsRefCount = 0;
let vpWsReconnectTimeoutId: ReturnType<typeof setTimeout> | null = null;
let tapeWsReconnectTimeoutId: ReturnType<typeof setTimeout> | null = null;
let vpWsBackoffMs = INITIAL_BACKOFF_MS;
let tapeWsBackoffMs = INITIAL_BACKOFF_MS;
let vpWsReady = false;
let tapeWsReady = false;

function flushTradeBatch(): void {
  tradeFlushTimeoutId = null;
  if (pendingTrades.length === 0) return;
  const batch = pendingTrades;
  pendingTrades = [];
  useMarketStore.getState().updateTradeBatch(batch);
}

function enqueueTrade(msg: TradeMessage): void {
  pendingTrades.push(msg);
  if (pendingTrades.length >= TRADE_BATCH_MAX) {
    if (tradeFlushTimeoutId != null) {
      clearTimeout(tradeFlushTimeoutId);
      tradeFlushTimeoutId = null;
    }
    flushTradeBatch();
    return;
  }
  if (tradeFlushTimeoutId == null) {
    tradeFlushTimeoutId = setTimeout(flushTradeBatch, 16);
  }
}

function flushDomSnapshot(): void {
  domFlushTimeoutId = null;
  if (pendingDomSnapshot == null) return;
  const last = pendingDomSnapshot;
  pendingDomSnapshot = null;
  useMarketStore.getState().updateDom(last);
}

function enqueueDomSnapshot(msg: DomSnapshotMessage): void {
  // DOM is stateful; keeping only the latest snapshot reduces render pressure.
  pendingDomSnapshot = msg;
  if (domFlushTimeoutId == null) {
    domFlushTimeoutId = setTimeout(flushDomSnapshot, 16);
  }
}

/** Quando false (ex.: Tauri antes do distributor subir), não tenta conectar; evita erro "closed before connection established". */
export function useWebSocket(enableConnection: boolean = true): void {
  const subscribedRef = useRef(false);
  const vpSubscribedRef = useRef(false);
  const tapeSubscribedRef = useRef(false);

  useEffect(() => {
    if (!enableConnection) {
      if (subscribedRef.current) {
        subscribedRef.current = false;
        wsRefCount--;
        if (wsRefCount <= 0) {
          wsRefCount = 0;
          if (tradeFlushTimeoutId != null) {
            clearTimeout(tradeFlushTimeoutId);
            tradeFlushTimeoutId = null;
          }
          pendingTrades = [];
          if (domFlushTimeoutId != null) {
            clearTimeout(domFlushTimeoutId);
            domFlushTimeoutId = null;
          }
          pendingDomSnapshot = null;
          if (wsReconnectTimeoutId) {
            clearTimeout(wsReconnectTimeoutId);
            wsReconnectTimeoutId = null;
          }
          if (sharedWs) {
            sharedWs.close();
            sharedWs = null;
          }
        }
      }
      if (vpSubscribedRef.current) {
        vpSubscribedRef.current = false;
        vpWsRefCount--;
        if (vpWsRefCount <= 0) {
          vpWsRefCount = 0;
          vpWsReady = false;
          if (vpWsReconnectTimeoutId) {
            clearTimeout(vpWsReconnectTimeoutId);
            vpWsReconnectTimeoutId = null;
          }
          if (sharedVpWs) {
            sharedVpWs.close();
            sharedVpWs = null;
          }
        }
      }
      if (tapeSubscribedRef.current) {
        tapeSubscribedRef.current = false;
        tapeWsRefCount--;
        if (tapeWsRefCount <= 0) {
          tapeWsRefCount = 0;
          tapeWsReady = false;
          if (tapeWsReconnectTimeoutId) {
            clearTimeout(tapeWsReconnectTimeoutId);
            tapeWsReconnectTimeoutId = null;
          }
          if (sharedTapeWs) {
            sharedTapeWs.close();
            sharedTapeWs = null;
          }
        }
      }
      useMarketStore.getState().setWsStatus("disconnected");
      return;
    }

    wsRefCount++;
    subscribedRef.current = true;
    vpWsRefCount++;
    tapeWsRefCount++;
    vpSubscribedRef.current = true;
    tapeSubscribedRef.current = true;

    const startTauriListeners = async () => {
      if (!isTauri()) return;
      if (tauriUnlistenTransport == null) {
        tauriUnlistenTransport = await listen<{ mode?: string }>(
          TAURI_IPC_TRANSPORT_EVENT,
          (ev) => {
            const mode = (ev.payload?.mode || "").toLowerCase();
            if (mode === "shm") {
              ipcTransportMode = "shm";
              useMarketStore.getState().setWsStatus("connected");
              void fetchWarmMacdSnapshot({
                retries: 6,
                retryDelayMs: 250,
              });
              if (!sharedWs || sharedWs.readyState !== WebSocket.OPEN) {
                connect();
              }
              return;
            }
            ipcTransportMode = "websocket";
            if (!sharedWs || sharedWs.readyState !== WebSocket.OPEN) {
              connect();
            }
          },
        );
      }
      if (tauriUnlistenMarket == null) {
        tauriUnlistenMarket = await listen<WsSingleMessage | WsBatchMessage>(
          TAURI_MARKET_EVENT,
          (ev) => {
            if (ipcTransportMode !== "shm") return;
            useMarketStore.getState().setWsStatus("connected");
            const p = ev.payload as WsMessage;
            if (p.topic === "ws_batch") {
              const batch = p as WsBatchMessage;
              const store = useMarketStore.getState();
              for (const item of batch.items) {
                dispatchWsPayload(item as WsSingleMessage, store);
              }
              return;
            }
            dispatchWsPayload(p as WsSingleMessage, useMarketStore.getState());
          },
        );
      }
      if (tauriUnlistenFallback == null) {
        tauriUnlistenFallback = await listen(TAURI_IPC_FALLBACK_EVENT, () => {
          ipcTransportMode = "websocket";
          if (!sharedWs || sharedWs.readyState !== WebSocket.OPEN) {
            connect();
          }
        });
      }
    };

    const connect = () => {
      if (wsRefCount <= 0) return;
      const store = useMarketStore.getState();
      store.setWsStatus("connecting");

      const url = getWsUrl();
      const ws = new WebSocket(url);
      sharedWs = ws;

      let connectTimeoutId: ReturnType<typeof setTimeout> | null = setTimeout(
        () => {
          connectTimeoutId = null;
          if (ws.readyState === WebSocket.CONNECTING) {
            ws.close();
          }
        },
        WS_CONNECT_TIMEOUT_MS,
      );

      ws.onopen = () => {
        if (connectTimeoutId) {
          clearTimeout(connectTimeoutId);
          connectTimeoutId = null;
        }
        wsBackoffMs = INITIAL_BACKOFF_MS;
        store.setWsStatus("connected");
        void fetchWarmMacdSnapshot({
          retries: 6,
          retryDelayMs: 250,
        });
      };

      ws.onmessage = (ev) => {
        handleMessage(ev.data, useMarketStore.getState(), {
          dropTrades: isTauri() && ipcTransportMode === "shm",
        });
      };

      ws.onclose = () => {
        if (connectTimeoutId) {
          clearTimeout(connectTimeoutId);
          connectTimeoutId = null;
        }
        if (sharedWs === ws) sharedWs = null;
        if (isTauri() && ipcTransportMode === "shm") {
          store.setWsStatus("connected");
        } else {
          store.setWsStatus("disconnected");
        }
        if (wsRefCount <= 0) return;
        const delay = Math.min(wsBackoffMs, MAX_BACKOFF_MS);
        wsBackoffMs = Math.min(wsBackoffMs * 2, MAX_BACKOFF_MS);
        wsReconnectTimeoutId = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    const connectVp = () => {
      if (vpWsRefCount <= 0) return;
      if (sharedVpWs && (sharedVpWs.readyState === WebSocket.OPEN || sharedVpWs.readyState === WebSocket.CONNECTING)) {
        return;
      }
      const ws = new WebSocket(getVpWsUrl());
      sharedVpWs = ws;
      ws.onopen = () => {
        vpWsBackoffMs = INITIAL_BACKOFF_MS;
        vpWsReady = true;
      };
      ws.onmessage = (ev) => {
        const store = useMarketStore.getState();
        if (typeof ev.data !== "string") return;
        try {
          const msg = JSON.parse(ev.data) as WsMessage;
          if (msg.topic === "ws_batch") {
            const batch = msg as WsBatchMessage;
            for (const item of batch.items) {
              if (item.topic === "market" && (item as { type?: string }).type === "volume_profile") {
                dispatchWsPayload(item, store, { forceVpTape: true });
              } else if (item.topic === "market" && (item as { type?: string }).type === "vp_overlay") {
                dispatchWsPayload(item, store);
              }
            }
            return;
          }
          if (msg.topic === "market" && (msg as { type?: string }).type === "volume_profile") {
            dispatchWsPayload(msg as WsSingleMessage, store, { forceVpTape: true });
          } else if (msg.topic === "market" && (msg as { type?: string }).type === "vp_overlay") {
            dispatchWsPayload(msg as WsSingleMessage, store);
          }
        } catch {
          // ignore parse errors
        }
      };
      ws.onclose = () => {
        if (sharedVpWs === ws) sharedVpWs = null;
        vpWsReady = false;
        if (vpWsRefCount <= 0) return;
        const delay = Math.min(vpWsBackoffMs, MAX_BACKOFF_MS);
        vpWsBackoffMs = Math.min(vpWsBackoffMs * 2, MAX_BACKOFF_MS);
        vpWsReconnectTimeoutId = setTimeout(connectVp, delay);
      };
      ws.onerror = () => ws.close();
    };

    const connectTape = () => {
      if (tapeWsRefCount <= 0) return;
      if (sharedTapeWs && (sharedTapeWs.readyState === WebSocket.OPEN || sharedTapeWs.readyState === WebSocket.CONNECTING)) {
        return;
      }
      const ws = new WebSocket(getTapeWsUrl());
      sharedTapeWs = ws;
      ws.onopen = () => {
        tapeWsBackoffMs = INITIAL_BACKOFF_MS;
        tapeWsReady = true;
      };
      ws.onmessage = (ev) => {
        const store = useMarketStore.getState();
        if (typeof ev.data !== "string") return;
        try {
          const msg = JSON.parse(ev.data) as WsMessage;
          if (msg.topic === "ws_batch") {
            const batch = msg as WsBatchMessage;
            for (const item of batch.items) {
              if (item.topic === "market" && (item as { type?: string }).type === "tape_intelligence") {
                dispatchWsPayload(item, store, { forceVpTape: true });
              } else if (item.topic === "market" && (item as { type?: string }).type === "vp_overlay") {
                dispatchWsPayload(item, store);
              }
            }
            return;
          }
          if (msg.topic === "market" && (msg as { type?: string }).type === "tape_intelligence") {
            dispatchWsPayload(msg as WsSingleMessage, store, { forceVpTape: true });
          } else if (msg.topic === "market" && (msg as { type?: string }).type === "vp_overlay") {
            dispatchWsPayload(msg as WsSingleMessage, store);
          }
        } catch {
          // ignore parse errors
        }
      };
      ws.onclose = () => {
        if (sharedTapeWs === ws) sharedTapeWs = null;
        tapeWsReady = false;
        if (tapeWsRefCount <= 0) return;
        const delay = Math.min(tapeWsBackoffMs, MAX_BACKOFF_MS);
        tapeWsBackoffMs = Math.min(tapeWsBackoffMs * 2, MAX_BACKOFF_MS);
        tapeWsReconnectTimeoutId = setTimeout(connectTape, delay);
      };
      ws.onerror = () => ws.close();
    };

    if (!sharedWs || sharedWs.readyState !== WebSocket.OPEN) {
      void startTauriListeners();
      connect();
    } else {
      useMarketStore.getState().setWsStatus("connected");
      void fetchWarmMacdSnapshot({
        retries: 6,
        retryDelayMs: 250,
      });
    }
    connectVp();
    connectTape();

    return () => {
      if (subscribedRef.current) {
        subscribedRef.current = false;
        wsRefCount--;
        if (wsRefCount <= 0) {
          wsRefCount = 0;
          if (tradeFlushTimeoutId != null) {
            clearTimeout(tradeFlushTimeoutId);
            tradeFlushTimeoutId = null;
          }
          pendingTrades = [];
          if (domFlushTimeoutId != null) {
            clearTimeout(domFlushTimeoutId);
            domFlushTimeoutId = null;
          }
          pendingDomSnapshot = null;
          if (wsReconnectTimeoutId) {
            clearTimeout(wsReconnectTimeoutId);
            wsReconnectTimeoutId = null;
          }
          if (sharedWs) {
            sharedWs.close();
            sharedWs = null;
          }
          if (tauriUnlistenMarket) {
            tauriUnlistenMarket();
            tauriUnlistenMarket = null;
          }
          if (tauriUnlistenTransport) {
            tauriUnlistenTransport();
            tauriUnlistenTransport = null;
          }
          if (tauriUnlistenFallback) {
            tauriUnlistenFallback();
            tauriUnlistenFallback = null;
          }
          ipcTransportMode = "unknown";
        }
      }
      if (vpSubscribedRef.current) {
        vpSubscribedRef.current = false;
        vpWsRefCount--;
        if (vpWsRefCount <= 0) {
          vpWsRefCount = 0;
          vpWsReady = false;
          if (vpWsReconnectTimeoutId) {
            clearTimeout(vpWsReconnectTimeoutId);
            vpWsReconnectTimeoutId = null;
          }
          if (sharedVpWs) {
            sharedVpWs.close();
            sharedVpWs = null;
          }
        }
      }
      if (tapeSubscribedRef.current) {
        tapeSubscribedRef.current = false;
        tapeWsRefCount--;
        if (tapeWsRefCount <= 0) {
          tapeWsRefCount = 0;
          tapeWsReady = false;
          if (tapeWsReconnectTimeoutId) {
            clearTimeout(tapeWsReconnectTimeoutId);
            tapeWsReconnectTimeoutId = null;
          }
          if (sharedTapeWs) {
            sharedTapeWs.close();
            sharedTapeWs = null;
          }
        }
      }
    };
  }, [enableConnection]);
}
