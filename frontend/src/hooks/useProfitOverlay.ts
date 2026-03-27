import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { OCR_WS_URL } from "../config/ocrPort";
import { useMarketStore } from "../store/marketStore";
import {
  computeAgentAggressorVwap,
  findUbsAgentId,
  roundToStep,
} from "../utils/ubs";
import {
  netSaldoAvgPrice,
  topBuyerByVolFin,
  topSellerByVolFin,
} from "../utils/agentVolume";

/** Arredondamento no eixo de preço do OCR (1 = genérico; WIN costuma ser múltiplo de 5 no book). */
const OVERLAY_CHART_PRICE_STEP = 1;

const STORAGE_SELECTED_METRICS = "pq-overlay-selected-metrics";

export type OverlayMetricId = "ubs" | "best_bid" | "best_ask";

export const OVERLAY_METRIC_ORDER: OverlayMetricId[] = [
  "ubs",
  "best_bid",
  "best_ask",
];

export const OVERLAY_METRIC_LABELS: Record<OverlayMetricId, string> = {
  ubs: "UBS",
  best_bid: "Líder comprador",
  best_ask: "Líder vendedor",
};

/** Cores alinhadas ao serviço OCR (profit_ocr_service). */
const OVERLAY_FALLBACK_COLORS = [
  "#00FF88",
  "#FF4444",
  "#FFB800",
  "#00CCFF",
  "#FF88FF",
  "#FFFFFF",
];

export function overlayLineColorForLabel(label: string, index: number): string {
  const s = label.trim().toLowerCase();
  if (s === "ubs") return "#A855F7";
  if (s.includes("vendedor") || (s.includes("venda") && !s.includes("compra")))
    return "#FF4444";
  if (s.includes("comprador") || s.includes("compra")) return "#00FF88";
  return OVERLAY_FALLBACK_COLORS[index % OVERLAY_FALLBACK_COLORS.length];
}

const DEFAULT_SELECTED_METRICS: OverlayMetricId[] = ["ubs", "best_bid", "best_ask"];

function loadSelectedMetrics(): OverlayMetricId[] {
  try {
    const raw = localStorage.getItem(STORAGE_SELECTED_METRICS);
    if (!raw) return [...DEFAULT_SELECTED_METRICS];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [...DEFAULT_SELECTED_METRICS];
    const allowed = new Set(OVERLAY_METRIC_ORDER);
    const next = parsed.filter((x): x is OverlayMetricId =>
      allowed.has(x as OverlayMetricId),
    );
    return next.length > 0 ? next : [...DEFAULT_SELECTED_METRICS];
  } catch {
    return [...DEFAULT_SELECTED_METRICS];
  }
}

function saveSelectedMetrics(ids: OverlayMetricId[]) {
  try {
    localStorage.setItem(STORAGE_SELECTED_METRICS, JSON.stringify(ids));
  } catch {
    // ignore
  }
}

export interface OverlayTarget {
  value: number;
  label: string;
  /** Definido para linhas derivadas de métricas; ausente em linhas manuais. */
  metricId?: OverlayMetricId;
}

export interface OverlayLine {
  value: number;
  y_screen: number;
  color: string;
  chart_left: number;
  chart_right: number;
  label?: string;
}

export interface OverlayState {
  active: boolean;
  status: string;
  targets: OverlayTarget[];
  lines: OverlayLine[];
  y_min: number | null;
  y_max: number | null;
}

function formatBrokerName(
  agentId: number | null,
  agentShortNames: Record<number, string>,
  agentNames: Record<number, string>,
): string | null {
  if (agentId == null) return null;
  const short = agentShortNames[agentId]?.trim();
  if (short) return short;
  const full = agentNames[agentId]?.trim();
  return full || null;
}

function targetsEqual(a: OverlayTarget[], b: OverlayTarget[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (
      a[i].value !== b[i].value ||
      a[i].label !== b[i].label ||
      a[i].metricId !== b[i].metricId
    ) {
      return false;
    }
  }
  return true;
}

export function useProfitOverlay() {
  const [state, setState] = useState<OverlayState>({
    active: false,
    status: "idle",
    targets: [],
    lines: [],
    y_min: null,
    y_max: null,
  });

  const [selectedMetricIds, setSelectedMetricIdsState] =
    useState<OverlayMetricId[]>(loadSelectedMetrics);

  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();
  const autoDynamicDefaultsRef = useRef(true);
  const wsRetryAttemptRef = useRef(0);
  const wsTotalRetryRef = useRef(0);
  const targetsRef = useRef<OverlayTarget[]>([]);
  const activeRef = useRef(false);
  const openStartMsRef = useRef<number | null>(null);
  const wsOpenLoggedRef = useRef(false);
  const firstOverlayLoggedRef = useRef(false);

  const vwap = useMarketStore((s) => s.vwap);
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);
  const agentBuyFinancial = useMarketStore((s) => s.agentBuyFinancial);
  const agentSellFinancial = useMarketStore((s) => s.agentSellFinancial);
  const agentShortNames = useMarketStore((s) => s.agentShortNames);
  const agentNames = useMarketStore((s) => s.agentNames);
  const domBuy = useMarketStore((s) => s.domBuy);
  const domSell = useMarketStore((s) => s.domSell);

  useEffect(() => {
    targetsRef.current = state.targets;
  }, [state.targets]);

  useEffect(() => {
    activeRef.current = state.active;
  }, [state.active]);

  const normalizePosition = useCallback(
    (value: number) => roundToStep(value, OVERLAY_CHART_PRICE_STEP),
    [],
  );

  const buildMetricTargets = useCallback((): OverlayTarget[] => {
    const out: OverlayTarget[] = [];
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
          : null;

    for (const id of OVERLAY_METRIC_ORDER) {
      if (!selectedMetricIds.includes(id)) continue;
      let raw: number | null = null;
      let label = OVERLAY_METRIC_LABELS[id];
      if (id === "ubs") {
        if (ubsPriceForChart != null && Number.isFinite(ubsPriceForChart)) {
          raw = normalizePosition(ubsPriceForChart);
        }
      } else if (id === "best_bid") {
        const leaderId = topBuyerByVolFin(
          agentBuyTotals,
          agentSellTotals,
          agentBuyFinancial,
          agentSellFinancial,
        );
        const p =
          leaderId == null
            ? null
            : netSaldoAvgPrice(
                leaderId,
                agentBuyTotals,
                agentSellTotals,
                agentBuyFinancial,
                agentSellFinancial,
              );
        raw = p != null ? normalizePosition(p) : null;
        const leader = formatBrokerName(
          leaderId,
          agentShortNames,
          agentNames,
        );
        if (leader) label = `${OVERLAY_METRIC_LABELS.best_bid} (${leader})`;
      } else if (id === "best_ask") {
        const leaderId = topSellerByVolFin(
          agentBuyTotals,
          agentSellTotals,
          agentBuyFinancial,
          agentSellFinancial,
        );
        const p =
          leaderId == null
            ? null
            : netSaldoAvgPrice(
                leaderId,
                agentBuyTotals,
                agentSellTotals,
                agentBuyFinancial,
                agentSellFinancial,
              );
        raw = p != null ? normalizePosition(p) : null;
        const leader = formatBrokerName(
          leaderId,
          agentShortNames,
          agentNames,
        );
        if (leader) label = `${OVERLAY_METRIC_LABELS.best_ask} (${leader})`;
      }
      if (raw == null || !Number.isFinite(raw) || raw <= 0) continue;
      out.push({
        value: raw,
        label,
        metricId: id,
      });
    }
    return out;
  }, [
    agentBuyFinancial,
    agentBuyTotals,
    agentNames,
    agentSellFinancial,
    agentSellTotals,
    agentShortNames,
    domBuy,
    domSell,
    normalizePosition,
    selectedMetricIds,
    vwap,
  ]);

  const mergeTargets = useCallback(
    (metrics: OverlayTarget[], manuals: OverlayTarget[]): OverlayTarget[] => [
      ...metrics,
      ...manuals,
    ],
    [],
  );

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (activeRef.current) {
      setState((prev) => ({
        ...prev,
        status: prev.status === "ok" ? prev.status : "connecting",
      }));
    }
    const ws = new WebSocket(OCR_WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      wsRetryAttemptRef.current = 0;
      wsTotalRetryRef.current = 0;
      if (!wsOpenLoggedRef.current && openStartMsRef.current != null) {
        const ms = Math.round(performance.now() - openStartMsRef.current);
        console.info(`[overlay-latency] ws_open elapsed_ms=${ms}`);
        wsOpenLoggedRef.current = true;
      }
      setState((prev) => {
        const valid = prev.targets.filter(
          (t) => Number.isFinite(t.value) && t.value > 0,
        );
        const payload = valid.map(({ value, label }) => ({ value, label }));
        ws.send(JSON.stringify({ type: "set_positions", targets: payload }));
        return { ...prev, status: "connecting" };
      });
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "overlay_update") {
          if (
            msg.data?.status === "ok" &&
            !firstOverlayLoggedRef.current &&
            openStartMsRef.current != null
          ) {
            const ms = Math.round(performance.now() - openStartMsRef.current);
            console.info(`[overlay-latency] first_overlay_ok elapsed_ms=${ms}`);
            firstOverlayLoggedRef.current = true;
          }
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
      wsTotalRetryRef.current += 1;
      const ms = delays[i] ?? 1500;
      if (activeRef.current) {
        setState((prev) => ({
          ...prev,
          status:
            wsTotalRetryRef.current > 10
              ? "ocr_unreachable_retrying"
              : "warming_up",
        }));
      }
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

  const pushTargets = useCallback((targets: OverlayTarget[]) => {
    const valid = targets.filter(
      (t) => Number.isFinite(t.value) && t.value > 0,
    );
    const payload = valid.map(({ value, label }) => ({ value, label }));
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ type: "set_positions", targets: payload }),
      );
      return;
    }
    invoke("set_overlay_positions", { targets: payload }).catch(() => {});
  }, []);

  const setSelectedMetricIds = useCallback((ids: OverlayMetricId[]) => {
    const allowed = new Set(OVERLAY_METRIC_ORDER);
    const next = ids.filter((id) => allowed.has(id));
    setSelectedMetricIdsState(next);
    saveSelectedMetrics(next);
    if (activeRef.current) autoDynamicDefaultsRef.current = true;
  }, []);

  const toggleMetric = useCallback((id: OverlayMetricId) => {
    setSelectedMetricIdsState((prev) => {
      const next = prev.includes(id)
        ? prev.filter((x) => x !== id)
        : [...prev, id];
      saveSelectedMetrics(next);
      return next;
    });
    if (activeRef.current) autoDynamicDefaultsRef.current = true;
  }, []);

  const openOverlay = useCallback(async () => {
    if (selectedMetricIds.length === 0) {
      console.warn("[overlay] Selecione ao menos um parâmetro para monitorar.");
      return;
    }
    try {
      openStartMsRef.current = performance.now();
      wsOpenLoggedRef.current = false;
      firstOverlayLoggedRef.current = false;
      setState((prev) => ({ ...prev, status: "warming_up" }));
      await invoke("open_profit_overlay");
      if (openStartMsRef.current != null) {
        const ms = Math.round(performance.now() - openStartMsRef.current);
        console.info(`[overlay-latency] open_profit_overlay_resolved elapsed_ms=${ms}`);
      }
      connectWs();
      autoDynamicDefaultsRef.current = true;
      const metrics = buildMetricTargets();
      const manuals = targetsRef.current.filter((t) => t.metricId == null);
      const next = mergeTargets(metrics, manuals);
      setState((prev) => ({ ...prev, active: true, targets: next }));
      pushTargets(next);
    } catch (err) {
      setState((prev) => ({ ...prev, status: "open_failed" }));
      console.error("[overlay] open_profit_overlay failed:", err);
    }
  }, [
    buildMetricTargets,
    connectWs,
    mergeTargets,
    pushTargets,
    selectedMetricIds,
  ]);

  const closeOverlay = useCallback(async () => {
    try {
      await invoke("close_profit_overlay");
      wsRef.current?.close();
      openStartMsRef.current = null;
      wsOpenLoggedRef.current = false;
      firstOverlayLoggedRef.current = false;
      setState((prev) => ({ ...prev, active: false, lines: [], status: "idle" }));
    } catch (err) {
      console.error("[overlay] close_profit_overlay failed:", err);
    }
  }, []);

  const setTargets = useCallback(
    (targets: OverlayTarget[]) => {
      autoDynamicDefaultsRef.current = false;
      const normalized = targets.map((t) => ({
        ...t,
        value: normalizePosition(t.value),
      }));
      setState((prev) => ({ ...prev, targets: normalized }));
      pushTargets(normalized);
    },
    [normalizePosition, pushTargets],
  );

  const addPosition = useCallback(
    (value: number) => {
      autoDynamicDefaultsRef.current = false;
      setState((prev) => {
        const manual: OverlayTarget = {
          value: normalizePosition(value),
          label: "Manual",
        };
        const next = [...prev.targets, manual];
        pushTargets(next);
        return { ...prev, targets: next };
      });
    },
    [normalizePosition, pushTargets],
  );

  const removePosition = useCallback(
    (index: number) => {
      autoDynamicDefaultsRef.current = false;
      setState((prev) => {
        const next = prev.targets.filter((_, i) => i !== index);
        pushTargets(next);
        return { ...prev, targets: next };
      });
    },
    [pushTargets],
  );

  const updatePosition = useCallback(
    (index: number, value: number) => {
      autoDynamicDefaultsRef.current = false;
      setState((prev) => {
        const next = prev.targets.map((p, i) =>
          i === index ? { ...p, value: normalizePosition(value) } : p,
        );
        pushTargets(next);
        return { ...prev, targets: next };
      });
    },
    [normalizePosition, pushTargets],
  );

  useEffect(() => {
    if (!state.active || !autoDynamicDefaultsRef.current) return;
    setState((prev) => {
      const manuals = prev.targets.filter((t) => t.metricId == null);
      const metrics = buildMetricTargets();
      const next = mergeTargets(metrics, manuals);
      if (targetsEqual(next, prev.targets)) return prev;
      pushTargets(next);
      return { ...prev, targets: next };
    });
  }, [
    buildMetricTargets,
    mergeTargets,
    pushTargets,
    state.active,
    vwap,
    domBuy,
    domSell,
    agentBuyFinancial,
    agentBuyTotals,
    agentNames,
    agentSellFinancial,
    agentSellTotals,
    agentShortNames,
    selectedMetricIds,
  ]);

  return {
    ...state,
    selectedMetricIds,
    setSelectedMetricIds,
    toggleMetric,
    openOverlay,
    closeOverlay,
    setTargets,
    addPosition,
    removePosition,
    updatePosition,
  };
}
