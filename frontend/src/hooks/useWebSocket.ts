import { useEffect, useRef } from "react";
import { useMarketStore } from "../store/marketStore";
import { isTauri } from "../utils/tauri";
import type {
  AlertMessage,
  DailyMessage,
  DomSnapshotMessage,
  FlowInversionMessage,
  MacdSignalMessage,
  SyncMessage,
  TradeMessage,
  WallAddMessage,
  WallRemoveMessage,
  WsMessage,
} from "../types/messages";

const MAX_BACKOFF_MS = 30000;
/** Intervalo mínimo entre o mesmo alerta (ticker|regra|direção) para evitar spam e duplicidade */
const ALERT_INTERVAL_MS = 60 * 1000;

const lastAlertByKey = new Map<string, number>();

function getAlertCooldownKey(alert: AlertMessage): string {
  return `${alert.ticker}|${alert.rule}|${alert.direction}`;
}
const INITIAL_BACKOFF_MS = 1000;
const WS_URL_TAURI = "ws://127.0.0.1:8000/ws";

function getWsUrl(): string {
  if (isTauri()) {
    return WS_URL_TAURI;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${protocol}//${host}/ws`;
}

function handleMessage(
  data: unknown,
  store: ReturnType<typeof useMarketStore.getState>,
): void {
  if (typeof data !== "string") return;
  try {
    const msg = JSON.parse(data) as WsMessage;

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

    if (msg.topic === "market") {
      const m = msg as { type: string; buy?: unknown[]; sell?: unknown[] };
      if (m.type === "trade") store.updateTrade(msg as TradeMessage);
      else if (m.type === "dom_snapshot")
        store.updateDom(msg as DomSnapshotMessage);
      else if (m.type === "wall_add") store.addWall(msg as WallAddMessage);
      else if (m.type === "wall_remove")
        store.removeWall(msg as WallRemoveMessage);
      else if (m.type === "daily") store.updateDaily(msg as DailyMessage);
      else if (m.type === "flow_inversion")
        store.addFlowInversion(msg as FlowInversionMessage);
      else if (m.type === "macd_signal") {
        // #region agent log
        const macdMsg = msg as MacdSignalMessage & { rsi?: number };
        fetch('http://127.0.0.1:7350/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'09d844'},body:JSON.stringify({sessionId:'09d844',location:'useWebSocket.ts:macd_signal',message:'macd_signal received',data:{hasRsi:macdMsg.rsi!=null,rsi:macdMsg.rsi},hypothesisId:'H1-H2-H5',timestamp:Date.now()})}).catch(()=>{});
        // #endregion
        store.updateMacd(msg as MacdSignalMessage);
      }
    }
  } catch {
    // ignore parse errors
  }
}

/** Quando false (ex.: Tauri antes do distributor subir), não tenta conectar; evita erro "closed before connection established". */
export function useWebSocket(enableConnection: boolean = true): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const backoffRef = useRef(INITIAL_BACKOFF_MS);

  useEffect(() => {
    if (!enableConnection) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      useMarketStore.getState().setWsStatus("disconnected");
      return;
    }

    const connect = () => {
      const store = useMarketStore.getState();
      store.setWsStatus("connecting");

      const url = getWsUrl();
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        backoffRef.current = INITIAL_BACKOFF_MS;
        store.setWsStatus("connected");
      };

      ws.onmessage = (ev) => {
        handleMessage(ev.data, useMarketStore.getState());
      };

      ws.onclose = () => {
        wsRef.current = null;
        store.setWsStatus("disconnected");
        const delay = Math.min(backoffRef.current, MAX_BACKOFF_MS);
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [enableConnection]);
}
