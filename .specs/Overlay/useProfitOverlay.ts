// frontend/src/hooks/useProfitOverlay.ts
//
// Hook que gerencia as posições do overlay e a comunicação
// com o serviço OCR via WebSocket + invoke Tauri.

import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

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

  // ── WS ─────────────────────────────────────────────────────────────────────
  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    const ws = new WebSocket(OCR_WS);
    wsRef.current = ws;

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
        /* ignore */
      }
    };

    ws.onclose = () => {
      retryTimer.current = setTimeout(connectWs, 1_500);
    };
    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      clearTimeout(retryTimer.current);
    };
  }, []);

  // ── Enviar posições via WS ──────────────────────────────────────────────────
  const pushPositions = useCallback((positions: number[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "set_positions", positions }));
    }
  }, []);

  // ── Abrir overlay ──────────────────────────────────────────────────────────
  const openOverlay = useCallback(async () => {
    try {
      await invoke("open_profit_overlay");
      connectWs();
      setState((prev) => ({ ...prev, active: true }));
    } catch (err) {
      console.error("[overlay] open_profit_overlay failed:", err);
    }
  }, [connectWs]);

  // ── Fechar overlay ─────────────────────────────────────────────────────────
  const closeOverlay = useCallback(async () => {
    try {
      await invoke("close_profit_overlay");
      wsRef.current?.close();
      setState((prev) => ({ ...prev, active: false, lines: [] }));
    } catch (err) {
      console.error("[overlay] close_profit_overlay failed:", err);
    }
  }, []);

  // ── Atualizar posições ─────────────────────────────────────────────────────
  const setPositions = useCallback(
    (positions: number[]) => {
      setState((prev) => ({ ...prev, positions }));
      pushPositions(positions);
    },
    [pushPositions],
  );

  const addPosition = useCallback(
    (value: number) => {
      setState((prev) => {
        const positions = [...prev.positions, value];
        pushPositions(positions);
        return { ...prev, positions };
      });
    },
    [pushPositions],
  );

  const removePosition = useCallback(
    (index: number) => {
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
      setState((prev) => {
        const positions = prev.positions.map((p, i) =>
          i === index ? value : p,
        );
        pushPositions(positions);
        return { ...prev, positions };
      });
    },
    [pushPositions],
  );

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
