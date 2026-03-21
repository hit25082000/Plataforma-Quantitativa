import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useMarketStore } from "../store/marketStore";
import {
  computeAgentAggressorVwap,
  findUbsAgentId,
  roundToStep,
} from "../utils/ubs";

/** Arredondamento no eixo de preço do OCR (1 = genérico; WIN costuma ser múltiplo de 5 no book). */
const OVERLAY_CHART_PRICE_STEP = 1;

const OCR_WS = "ws://127.0.0.1:5558/ws";

export interface OverlayLine {
  value: number;
  y_screen: number;
  color: string;
  chart_left: number;
  chart_right: number;
}

export interface OverlayState {
  active: boolean;
  status: string;
  positions: number[];
  lines: OverlayLine[];
  y_min: number | null;
  y_max: number | null;
}

export function useProfitOverlay() {
  const [state, setState] = useState<OverlayState>({
    active: false,
    status: "idle",
    positions: [],
    lines: [],
    y_min: null,
    y_max: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();
  const autoDynamicDefaultsRef = useRef(true);
  const wsRetryAttemptRef = useRef(0);

  const vwap = useMarketStore((s) => s.vwap);
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);
  const agentBuyFinancial = useMarketStore((s) => s.agentBuyFinancial);
  const agentSellFinancial = useMarketStore((s) => s.agentSellFinancial);
  const agentShortNames = useMarketStore((s) => s.agentShortNames);
  const agentNames = useMarketStore((s) => s.agentNames);

  const normalizePosition = useCallback(
    (value: number) => roundToStep(value, OVERLAY_CHART_PRICE_STEP),
    [],
  );

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    const ws = new WebSocket(OCR_WS);
    wsRef.current = ws;

    ws.onopen = () => {
      wsRetryAttemptRef.current = 0;
      // Reenvia estado atual ao conectar para nao perder set_positions enviado cedo.
      setState((prev) => {
        ws.send(JSON.stringify({ type: "set_positions", positions: prev.positions }));
        return prev;
      });
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "overlay_update") {
          setState((prev) => ({
            ...prev,
            status: msg.data.status,
            lines: msg.data.lines ?? [],
            y_min: msg.data.y_min ?? null,
            y_max: msg.data.y_max ?? null,
          }));
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      const delays = [200, 350, 600, 1000, 1500];
      const i = Math.min(wsRetryAttemptRef.current++, delays.length - 1);
      const ms = delays[i] ?? 1500;
      clearTimeout(retryTimer.current);
      retryTimer.current = setTimeout(connectWs, ms);
    };
    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      clearTimeout(retryTimer.current);
    };
  }, []);

  const pushPositions = useCallback((positions: number[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "set_positions", positions }));
    }
    // Fallback deterministico: garante sincronizacao no OCR mesmo sem WS aberto.
    invoke("set_overlay_positions", { positions }).catch(() => {});
  }, []);

  const buildDefaultPositions = useCallback((): number[] => {
    const avgPrice = vwap;

    const ubsId = findUbsAgentId(agentShortNames, agentNames);
    const ubsVwap =
      ubsId == null
        ? null
        : computeAgentAggressorVwap(
            ubsId,
            agentBuyTotals,
            agentSellTotals,
            agentBuyFinancial,
            agentSellFinancial,
          );
    const ubsPriceForChart =
      ubsVwap != null && Number.isFinite(ubsVwap)
        ? ubsVwap
        : Number.isFinite(avgPrice) && avgPrice > 0
          ? avgPrice
          : 0;

    const avgSafe = Number.isFinite(avgPrice) ? normalizePosition(avgPrice) : 0;
    const ubsSafe = Number.isFinite(ubsPriceForChart)
      ? normalizePosition(ubsPriceForChart)
      : avgSafe;
    return [avgSafe, ubsSafe];
  }, [
    agentBuyFinancial,
    agentBuyTotals,
    agentNames,
    agentSellFinancial,
    agentSellTotals,
    agentShortNames,
    normalizePosition,
    vwap,
  ]);

  const openOverlay = useCallback(async () => {
    try {
      await invoke("open_profit_overlay");
      connectWs();
      const positions = buildDefaultPositions();
      autoDynamicDefaultsRef.current = true;
      setState((prev) => ({ ...prev, active: true, positions }));
      pushPositions(positions);
    } catch (err) {
      console.error("[overlay] open_profit_overlay failed:", err);
    }
  }, [buildDefaultPositions, connectWs, pushPositions]);

  const closeOverlay = useCallback(async () => {
    try {
      await invoke("close_profit_overlay");
      wsRef.current?.close();
      setState((prev) => ({ ...prev, active: false, lines: [] }));
    } catch (err) {
      console.error("[overlay] close_profit_overlay failed:", err);
    }
  }, []);

  const setPositions = useCallback(
    (positions: number[]) => {
      autoDynamicDefaultsRef.current = false;
      const normalized = positions.map(normalizePosition);
      setState((prev) => ({ ...prev, positions: normalized }));
      pushPositions(normalized);
    },
    [normalizePosition, pushPositions],
  );

  const addPosition = useCallback(
    (value: number) => {
      autoDynamicDefaultsRef.current = false;
      setState((prev) => {
        const positions = [...prev.positions, normalizePosition(value)];
        pushPositions(positions);
        return { ...prev, positions };
      });
    },
    [normalizePosition, pushPositions],
  );

  const removePosition = useCallback(
    (index: number) => {
      autoDynamicDefaultsRef.current = false;
      setState((prev) => {
        const positions = prev.positions.filter((_, i) => i !== index);
        pushPositions(positions);
        return { ...prev, positions };
      });
    },
    [pushPositions],
  );

  const updatePosition = useCallback(
    (index: number, value: number) => {
      autoDynamicDefaultsRef.current = false;
      setState((prev) => {
        const positions = prev.positions.map((p, i) => (i === index ? normalizePosition(value) : p));
        pushPositions(positions);
        return { ...prev, positions };
      });
    },
    [normalizePosition, pushPositions],
  );

  useEffect(() => {
    if (!state.active || !autoDynamicDefaultsRef.current) return;
    const next = buildDefaultPositions();
    const same =
      state.positions.length === 2 &&
      state.positions[0] === next[0] &&
      state.positions[1] === next[1];
    if (same) return;
    setState((prev) => ({ ...prev, positions: next }));
    pushPositions(next);
  }, [buildDefaultPositions, pushPositions, state.active, state.positions]);

  return {
    ...state,
    openOverlay,
    closeOverlay,
    setPositions,
    addPosition,
    removePosition,
    updatePosition,
  };
}
