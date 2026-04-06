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
  TradeMessage,
  WallAddMessage,
  WallRemoveMessage,
  WsBatchMessage,
  WsMessage,
  WsSingleMessage,
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
const TRADE_BATCH_MAX = 200;

function getWsUrl(): string {
  if (isTauri()) {
    return WS_URL_TAURI;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${protocol}//${host}/ws`;
}

function dispatchWsPayload(
  msg: WsSingleMessage,
  store: ReturnType<typeof useMarketStore.getState>,
): void {
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
): void {
  if (typeof data !== "string") return;
  try {
    const msg = JSON.parse(data) as WsMessage;
    if (msg.topic === "ws_batch") {
      const batch = msg as WsBatchMessage;
      for (const item of batch.items) {
        dispatchWsPayload(item, store);
      }
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
let tradeFlushRafId: number | null = null;
let pendingDomSnapshot: DomSnapshotMessage | null = null;
let domFlushRafId: number | null = null;

function flushTradeBatch(): void {
  tradeFlushRafId = null;
  if (pendingTrades.length === 0) return;
  const batch = pendingTrades;
  pendingTrades = [];
  useMarketStore.getState().updateTradeBatch(batch);
}

function enqueueTrade(msg: TradeMessage): void {
  pendingTrades.push(msg);
  if (pendingTrades.length >= TRADE_BATCH_MAX) {
    if (tradeFlushRafId != null) {
      window.cancelAnimationFrame(tradeFlushRafId);
      tradeFlushRafId = null;
    }
    flushTradeBatch();
    return;
  }
  if (tradeFlushRafId == null) {
    tradeFlushRafId = window.requestAnimationFrame(flushTradeBatch);
  }
}

function flushDomSnapshot(): void {
  domFlushRafId = null;
  if (pendingDomSnapshot == null) return;
  const last = pendingDomSnapshot;
  pendingDomSnapshot = null;
  useMarketStore.getState().updateDom(last);
}

function enqueueDomSnapshot(msg: DomSnapshotMessage): void {
  // DOM is stateful; keeping only the latest snapshot reduces render pressure.
  pendingDomSnapshot = msg;
  if (domFlushRafId == null) {
    domFlushRafId = window.requestAnimationFrame(flushDomSnapshot);
  }
}

/** Quando false (ex.: Tauri antes do distributor subir), não tenta conectar; evita erro "closed before connection established". */
export function useWebSocket(enableConnection: boolean = true): void {
  const subscribedRef = useRef(false);

  useEffect(() => {
    if (!enableConnection) {
      if (subscribedRef.current) {
        subscribedRef.current = false;
        wsRefCount--;
        if (wsRefCount <= 0) {
          wsRefCount = 0;
          if (tradeFlushRafId != null) {
            window.cancelAnimationFrame(tradeFlushRafId);
            tradeFlushRafId = null;
          }
          pendingTrades = [];
          if (domFlushRafId != null) {
            window.cancelAnimationFrame(domFlushRafId);
            domFlushRafId = null;
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
      useMarketStore.getState().setWsStatus("disconnected");
      return;
    }

    wsRefCount++;
    subscribedRef.current = true;

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
        void fetchWarmMacdSnapshot();
      };

      ws.onmessage = (ev) => {
        handleMessage(ev.data, useMarketStore.getState());
      };

      ws.onclose = () => {
        if (connectTimeoutId) {
          clearTimeout(connectTimeoutId);
          connectTimeoutId = null;
        }
        if (sharedWs === ws) sharedWs = null;
        store.setWsStatus("disconnected");
        if (wsRefCount <= 0) return;
        const delay = Math.min(wsBackoffMs, MAX_BACKOFF_MS);
        wsBackoffMs = Math.min(wsBackoffMs * 2, MAX_BACKOFF_MS);
        wsReconnectTimeoutId = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    if (!sharedWs || sharedWs.readyState !== WebSocket.OPEN) {
      connect();
    } else {
      useMarketStore.getState().setWsStatus("connected");
      void fetchWarmMacdSnapshot();
    }

    return () => {
      if (subscribedRef.current) {
        subscribedRef.current = false;
        wsRefCount--;
        if (wsRefCount <= 0) {
          wsRefCount = 0;
          if (tradeFlushRafId != null) {
            window.cancelAnimationFrame(tradeFlushRafId);
            tradeFlushRafId = null;
          }
          pendingTrades = [];
          if (domFlushRafId != null) {
            window.cancelAnimationFrame(domFlushRafId);
            domFlushRafId = null;
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
    };
  }, [enableConnection]);
}
