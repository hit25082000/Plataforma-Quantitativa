import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { OCR_WS_URL, ocrWsUrlFromPort } from "../config/ocrPort";
import { useMarketStore } from "../store/marketStore";
import type { VolumeProfileMessage } from "../types/messages";
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
import type { OcrAxisDeltasOrLegacy } from "../utils/ocrStatus";
import { parseOverlayUpdatePayload } from "../utils/overlayUpdateCompat";

/** Arredondamento no eixo de preço do OCR (1 = genérico; WIN costuma ser múltiplo de 5 no book). */
const OVERLAY_CHART_PRICE_STEP = 1;

const STORAGE_SELECTED_METRICS = "pq-overlay-selected-metrics";
const OPEN_OVERLAY_TIMEOUT_MS = 45_000;

export type OverlayMetricId = "ubs" | "best_bid" | "best_ask";

export const OVERLAY_METRIC_ORDER: OverlayMetricId[] = [];

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

const DEFAULT_SELECTED_METRICS: OverlayMetricId[] = [];

function normalizeSymbol(symbol?: string | null): string {
  if (!symbol) return "";
  const s = symbol.trim().toUpperCase();
  const base = s.split("·")[0]?.trim() ?? s;
  if (base === "WIN" || base === "WINFUT" || /^WIN[A-Z]\d{2}$/i.test(base)) return "WINFUT";
  if (base === "IND" || base === "INDFUT" || /^IND[A-Z]\d{2}$/i.test(base)) return "INDFUT";
  return base;
}

function buildVolumeProfileTargets(vp: VolumeProfileMessage | null): OverlayTarget[] {
  if (!vp || !Number.isFinite(vp.total_vol) || vp.total_vol <= 0) return [];
  const out: OverlayTarget[] = [];
  if (typeof vp.poc === "number" && Number.isFinite(vp.poc)) {
    out.push({ value: vp.poc, label: "VP POC" });
  }
  if (typeof vp.vah === "number" && Number.isFinite(vp.vah)) {
    out.push({ value: vp.vah, label: "VP VAH" });
  }
  if (typeof vp.val === "number" && Number.isFinite(vp.val)) {
    out.push({ value: vp.val, label: "VP VAL" });
  }
  return out;
}

function debugOverlayLog(
  runId: string,
  hypothesisId: string,
  location: string,
  message: string,
  data: Record<string, unknown>,
) {
  // #region agent log
  fetch("http://127.0.0.1:7895/ingest/74027e3c-6845-4f2c-85c1-20fad01d1448", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "9b12fa" },
    body: JSON.stringify({
      sessionId: "9b12fa",
      runId,
      hypothesisId,
      location,
      message,
      data,
      timestamp: Date.now(),
    }),
  }).catch(() => {});
  // #endregion
}

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
  source?: "manual" | "metric" | "vp";
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

/** Região opcional só para leitura OCR (painéis do Profit); não define posição das linhas. */
export interface OcrAnalysisRoi {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface OcrAnalysisSample {
  text?: string;
  numbers?: number[];
  ts?: number;
  error?: string;
  tesseract_error?: string;
}

export interface OverlayState {
  active: boolean;
  /** True enquanto `open_profit_overlay` está em curso (OCR + janelas). */
  activating: boolean;
  status: string;
  targets: OverlayTarget[];
  lines: OverlayLine[];
  y_min: number | null;
  y_max: number | null;
  axis_deltas: OcrAxisDeltasOrLegacy | null;
  axis_diagnostics: Record<string, unknown> | null;
  analysisRoi: OcrAnalysisRoi | null;
  analysisSample: OcrAnalysisSample | null;
  axis_error_code: string | null;
  axis_error_message: string | null;
  last_good_axis_age_ms: number | null;
  overlay_window_alive: boolean | null;
  ocr_service_alive: boolean | null;
  ocr_ws_connected: boolean | null;
  vp_status: string | null;
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
      a[i].source !== b[i].source ||
      a[i].metricId !== b[i].metricId
    ) {
      return false;
    }
  }
  return true;
}

function isManualTarget(t: OverlayTarget): boolean {
  if (t.source != null) return t.source === "manual";
  return t.metricId == null && t.label === "Manual";
}

export function useProfitOverlay() {
  const [state, setState] = useState<OverlayState>({
    active: false,
    activating: false,
    status: "idle",
    targets: [],
    lines: [],
    y_min: null,
    y_max: null,
    axis_deltas: null,
    axis_diagnostics: null,
    analysisRoi: null,
    analysisSample: null,
    axis_error_code: null,
    axis_error_message: null,
    last_good_axis_age_ms: null,
    overlay_window_alive: null,
    ocr_service_alive: null,
    ocr_ws_connected: null,
    vp_status: null,
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
  /** Evita alternar líder comprador/vendedor a cada tick quando o saldo fin. está quase empatado. */
  const stableBuyerLeaderRef = useRef<number | null>(null);
  const stableSellerLeaderRef = useRef<number | null>(null);
  const autoPushTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const pendingAutoPushRef = useRef<OverlayTarget[] | null>(null);
  /** Só altera preço enviado ao OCR após 2 ticks iguais — corta oscilação 100↔101↔100. */
  const overlayMetricSlotRef = useRef<
    Partial<
      Record<
        OverlayMetricId,
        { pending: number; streak: number; committed: number | null }
      >
    >
  >({});

  const vwap = useMarketStore((s) => s.vwap);
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);
  const agentBuyFinancial = useMarketStore((s) => s.agentBuyFinancial);
  const agentSellFinancial = useMarketStore((s) => s.agentSellFinancial);
  const agentShortNames = useMarketStore((s) => s.agentShortNames);
  const agentNames = useMarketStore((s) => s.agentNames);
  const volumeProfile = useMarketStore((s) => s.volumeProfile);
  const selectedTicker = useMarketStore((s) => s.selectedTicker);
  useEffect(() => {
    targetsRef.current = state.targets;
  }, [state.targets]);

  useEffect(() => {
    activeRef.current = state.active;
  }, [state.active]);

  /** ROI de análise persistida em config.json — mostrar mesmo antes de ligar o WebSocket. */
  useEffect(() => {
    let cancelled = false;
    invoke<{
      ocr_analysis_roi?: {
        left: number;
        top: number;
        width: number;
        height: number;
      } | null;
    }>("read_config")
      .then((cfg) => {
        if (cancelled) return;
        const r = cfg.ocr_analysis_roi;
        if (
          r &&
          typeof r.width === "number" &&
          typeof r.height === "number" &&
          r.width >= 4 &&
          r.height >= 4
        ) {
          setState((p) => ({
            ...p,
            analysisRoi: {
              left: r.left,
              top: r.top,
              width: r.width,
              height: r.height,
            },
          }));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const normalizePosition = useCallback(
    (value: number) => roundToStep(value, OVERLAY_CHART_PRICE_STEP),
    [],
  );

  const buildMetricTargets = useCallback((): OverlayTarget[] => {
    if (selectedMetricIds.length === 0) return [];

    const saldoFin = (agentId: number) =>
      Number(agentBuyFinancial[agentId] ?? 0) -
      Number(agentSellFinancial[agentId] ?? 0);

    const pickStableBuyer = (raw: number | null): number | null => {
      if (raw == null) {
        stableBuyerLeaderRef.current = null;
        return null;
      }
      const rFin = saldoFin(raw);
      if (!(rFin > 0)) {
        stableBuyerLeaderRef.current = null;
        return null;
      }
      const prev = stableBuyerLeaderRef.current;
      if (prev == null || prev === raw) {
        stableBuyerLeaderRef.current = raw;
        return raw;
      }
      const pFin = saldoFin(prev);
      const margin = Math.max(1, Math.abs(pFin) * 0.0025);
      if (rFin >= pFin + margin) {
        stableBuyerLeaderRef.current = raw;
        return raw;
      }
      return prev;
    };

    const pickStableSeller = (raw: number | null): number | null => {
      if (raw == null) {
        stableSellerLeaderRef.current = null;
        return null;
      }
      const rFin = saldoFin(raw);
      if (!(rFin < 0)) {
        stableSellerLeaderRef.current = null;
        return null;
      }
      const prev = stableSellerLeaderRef.current;
      if (prev == null || prev === raw) {
        stableSellerLeaderRef.current = raw;
        return raw;
      }
      const pFin = saldoFin(prev);
      const margin = Math.max(1, Math.abs(pFin) * 0.0025);
      if (rFin <= pFin - margin) {
        stableSellerLeaderRef.current = raw;
        return raw;
      }
      return prev;
    };

    const commitOverlayMetricPrice = (mid: OverlayMetricId, v: number): number => {
      const cur = overlayMetricSlotRef.current[mid];
      if (cur == null || cur.committed == null) {
        overlayMetricSlotRef.current[mid] = { pending: v, streak: 1, committed: v };
        return v;
      }
      if (v === cur.committed) {
        overlayMetricSlotRef.current[mid] = { pending: v, streak: 1, committed: v };
        return v;
      }
      if (v !== cur.pending) {
        overlayMetricSlotRef.current[mid] = {
          pending: v,
          streak: 1,
          committed: cur.committed,
        };
        return cur.committed;
      }
      const streak = cur.streak + 1;
      if (streak >= 2) {
        overlayMetricSlotRef.current[mid] = { pending: v, streak: 2, committed: v };
        return v;
      }
      overlayMetricSlotRef.current[mid] = {
        pending: v,
        streak,
        committed: cur.committed,
      };
      return cur.committed;
    };

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
          raw = commitOverlayMetricPrice("ubs", normalizePosition(ubsPriceForChart));
        }
      } else if (id === "best_bid") {
        const rawLeader = topBuyerByVolFin(
          agentBuyTotals,
          agentSellTotals,
          agentBuyFinancial,
          agentSellFinancial,
        );
        const leaderId = pickStableBuyer(rawLeader);
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
        raw =
          p != null
            ? commitOverlayMetricPrice("best_bid", normalizePosition(p))
            : null;
        const leader = formatBrokerName(
          leaderId,
          agentShortNames,
          agentNames,
        );
        if (leader) label = `${OVERLAY_METRIC_LABELS.best_bid} (${leader})`;
      } else if (id === "best_ask") {
        const rawLeader = topSellerByVolFin(
          agentBuyTotals,
          agentSellTotals,
          agentBuyFinancial,
          agentSellFinancial,
        );
        const leaderId = pickStableSeller(rawLeader);
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
        raw =
          p != null
            ? commitOverlayMetricPrice("best_ask", normalizePosition(p))
            : null;
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
        source: "metric",
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
    normalizePosition,
    selectedMetricIds,
    vwap,
  ]);

  useEffect(() => {
    stableBuyerLeaderRef.current = null;
    stableSellerLeaderRef.current = null;
    overlayMetricSlotRef.current = {};
  }, [selectedMetricIds]);

  const mergeTargets = useCallback(
    (metrics: OverlayTarget[], vp: OverlayTarget[], manuals: OverlayTarget[]): OverlayTarget[] => [
      ...metrics,
      ...vp,
      ...manuals,
    ],
    [],
  );

  const connectWs = useCallback(() => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }
    if (activeRef.current) {
      setState((prev) => ({
        ...prev,
        status: prev.status === "ok" ? prev.status : "connecting",
      }));
    }
    let cancelled = false;
    const openWs = async () => {
      let wsUrl = OCR_WS_URL;
      try {
        const runtimePort = await invoke<number>("get_ocr_runtime_port");
        if (Number.isFinite(runtimePort) && runtimePort > 0) {
          wsUrl = ocrWsUrlFromPort(runtimePort);
        }
      } catch {
        // fallback para porta estática
      }
      if (cancelled) return;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        wsRetryAttemptRef.current = 0;
        wsTotalRetryRef.current = 0;
        if (!wsOpenLoggedRef.current && openStartMsRef.current != null) {
          const ms = Math.round(performance.now() - openStartMsRef.current);
          console.info(`[overlay-metric] ws_ocr_open_ms=${ms}`);
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
          const parsed = parseOverlayUpdatePayload(msg);
          if (parsed) {
            // #region agent log
            debugOverlayLog("pre-fix", "H6", "useProfitOverlay.ts:513", "ocr_overlay_update", {
              status: parsed.status,
              lineCount: parsed.lines.length,
              yMin: parsed.yMin,
              yMax: parsed.yMax,
              axisKeptLabels: parsed.axisDiagnostics?.kept_labels ?? null,
              axisRejected: parsed.axisDiagnostics?.rejected ?? null,
            });
            // #endregion
            if (
              parsed.status === "ok" &&
              !firstOverlayLoggedRef.current &&
              openStartMsRef.current != null
            ) {
              const ms = Math.round(performance.now() - openStartMsRef.current);
              console.info(`[overlay-latency] first_overlay_ok elapsed_ms=${ms}`);
              firstOverlayLoggedRef.current = true;
            }
            setState((prev) => ({
              ...prev,
              status: parsed.status,
              lines: parsed.lines,
              y_min: parsed.yMin,
              y_max: parsed.yMax,
              axis_deltas: parsed.axisDeltas,
              axis_diagnostics: parsed.axisDiagnostics,
              analysisRoi: (parsed.analysisRoi as OcrAnalysisRoi | null | undefined) ?? null,
              analysisSample: (parsed.analysisSample as OcrAnalysisSample | null | undefined) ?? null,
              axis_error_code: parsed.axisErrorCode,
              axis_error_message: parsed.axisErrorMessage,
              last_good_axis_age_ms: parsed.lastGoodAxisAgeMs,
              overlay_window_alive: parsed.overlayWindowAlive,
              ocr_service_alive: parsed.ocrServiceAlive,
              ocr_ws_connected: parsed.ocrWsConnected,
              vp_status: parsed.vpStatus,
            }));
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        const delays = [
          250, 500, 800, 1200, 1600, 2000, 2500, 3000, 3500, 4000, 4500,
        ];
        const i = Math.min(wsRetryAttemptRef.current++, delays.length - 1);
        wsTotalRetryRef.current += 1;
        const ms = (delays[i] ?? 4500) + Math.floor(Math.random() * 120);
        if (activeRef.current) {
          setState((prev) => ({
            ...prev,
            status:
              wsTotalRetryRef.current > 32
                ? "ocr_unreachable_retrying"
                : "warming_up",
          }));
        }
        clearTimeout(retryTimer.current);
        retryTimer.current = setTimeout(connectWs, ms);
      };
      ws.onerror = () => ws.close();
    };
    void openWs();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void invoke("prewarm_profit_ocr").catch(() => {});
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
    // #region agent log
    debugOverlayLog("pre-fix", "H5", "useProfitOverlay.ts:581", "push_targets_called", {
      targetCount: targets.length,
      validCount: valid.length,
      wsState: wsRef.current?.readyState ?? -1,
      sample: payload.slice(0, 4),
    });
    // #endregion
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ type: "set_positions", targets: payload }),
      );
      return;
    }
    invoke("set_overlay_positions", { targets: payload }).catch(() => {});
  }, []);

  /** Agrupa atualizações do stream (ticks) num único set_positions para o OCR. */
  const scheduleAutoPushTargets = useCallback((targets: OverlayTarget[]) => {
    pendingAutoPushRef.current = targets;
    clearTimeout(autoPushTimerRef.current);
    autoPushTimerRef.current = setTimeout(() => {
      const t = pendingAutoPushRef.current;
      pendingAutoPushRef.current = null;
      if (!t || !activeRef.current) return;
      pushTargets(t);
    }, 90);
  }, [pushTargets]);

  useEffect(() => {
    const onMouseDown = (ev: MouseEvent) => {
      if (ev.button !== 0) return;
      if (!activeRef.current) return;
      const currentTargets = targetsRef.current;
      // #region agent log
      debugOverlayLog(
        "post-fix",
        "H12",
        "useProfitOverlay.ts:650",
        "left_click_force_push_targets",
        {
          targetCount: currentTargets.length,
          wsState: wsRef.current?.readyState ?? -1,
        },
      );
      // #endregion
      pushTargets(currentTargets);
    };
    window.addEventListener("mousedown", onMouseDown, true);
    return () => {
      window.removeEventListener("mousedown", onMouseDown, true);
    };
  }, [pushTargets]);

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
    try {
      openStartMsRef.current = performance.now();
      wsOpenLoggedRef.current = false;
      firstOverlayLoggedRef.current = false;
      setState((prev) => ({
        ...prev,
        status: "warming_up",
        activating: true,
      }));
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(() => {
          reject(
            new Error(
              "Tempo limite ao iniciar Overlay/OCR. Abra Configurações > Abrir pasta de logs e verifique runtime-bootstrap.log/profit_ocr_stderr.log.",
            ),
          );
        }, OPEN_OVERLAY_TIMEOUT_MS);
        invoke<{ ok?: boolean; windows_ready_ms?: number; ocr_mode?: string }>("open_profit_overlay")
          .then((result) => {
            if (typeof result?.windows_ready_ms === "number") {
              console.info(`[overlay-metric] windows_ready_ms=${Math.round(result.windows_ready_ms)}`);
            }
            window.clearTimeout(timer);
            resolve();
          })
          .catch((err) => {
            window.clearTimeout(timer);
            reject(err);
          });
      });
      if (openStartMsRef.current != null) {
        const ms = Math.round(performance.now() - openStartMsRef.current);
        console.info(`[overlay-latency] open_profit_overlay_resolved elapsed_ms=${ms}`);
      }
      stableBuyerLeaderRef.current = null;
      stableSellerLeaderRef.current = null;
      overlayMetricSlotRef.current = {};
      connectWs();
      autoDynamicDefaultsRef.current = true;
      const metrics = buildMetricTargets();
      const selected = normalizeSymbol(selectedTicker);
      const incoming = normalizeSymbol(volumeProfile?.ticker);
      const vpTargets =
        incoming !== "" && selected !== "" && incoming === selected
          ? buildVolumeProfileTargets(volumeProfile).map((t) => ({
              ...t,
              value: normalizePosition(t.value),
              source: "vp" as const,
            }))
          : [];
      const manuals = targetsRef.current.filter(isManualTarget);
      const next = mergeTargets(metrics, vpTargets, manuals);
      setState((prev) => ({
        ...prev,
        active: true,
        activating: false,
        targets: next,
      }));
      pushTargets(next);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err ?? "");
      const userFacing =
        msg && msg.length > 0
          ? `open_failed: ${msg}`
          : "open_failed";
      setState((prev) => ({
        ...prev,
        activating: false,
        status: userFacing,
      }));
      console.error("[overlay] open_profit_overlay failed:", err);
    }
  }, [
    buildMetricTargets,
    connectWs,
    mergeTargets,
    normalizePosition,
    pushTargets,
    selectedTicker,
    selectedMetricIds,
    volumeProfile,
  ]);

  const closeOverlay = useCallback(async () => {
    try {
      await invoke("close_profit_overlay", { reason: "overlay_control_toggle_off" });
      clearTimeout(autoPushTimerRef.current);
      pendingAutoPushRef.current = null;
      stableBuyerLeaderRef.current = null;
      stableSellerLeaderRef.current = null;
      overlayMetricSlotRef.current = {};
      wsRef.current?.close();
      openStartMsRef.current = null;
      wsOpenLoggedRef.current = false;
      firstOverlayLoggedRef.current = false;
      setState((prev) => ({
        ...prev,
        active: false,
        activating: false,
        lines: [],
        status: "idle",
      }));
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
          source: "manual",
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

  const openOcrRoiPicker = useCallback(async () => {
    try {
      await invoke("open_ocr_roi_picker");
    } catch (err) {
      console.error("[overlay] open_ocr_roi_picker failed:", err);
    }
  }, []);

  const clearOcrAnalysisRoi = useCallback(async () => {
    try {
      await invoke("clear_ocr_analysis_roi");
      setState((prev) => ({ ...prev, analysisRoi: null, analysisSample: null }));
    } catch (err) {
      console.error("[overlay] clear_ocr_analysis_roi failed:", err);
    }
  }, []);

  useEffect(() => {
    if (!state.active || !autoDynamicDefaultsRef.current) return;
    setState((prev) => {
      const manuals = prev.targets.filter(isManualTarget);
      const metrics = buildMetricTargets();
      const selected = normalizeSymbol(selectedTicker);
      const incoming = normalizeSymbol(volumeProfile?.ticker);
      const vpTargets =
        incoming !== "" && selected !== "" && incoming === selected
          ? buildVolumeProfileTargets(volumeProfile).map((t) => ({
              ...t,
              value: normalizePosition(t.value),
              source: "vp" as const,
            }))
          : [];
      if (vpTargets.length > 0) {
        console.debug(
          `[VP_OVERLAY] targets=${vpTargets.length} prices=${vpTargets.map((t) => t.value).join(",")}`,
        );
      }
      const next = mergeTargets(metrics, vpTargets, manuals);
      if (targetsEqual(next, prev.targets)) return prev;
      scheduleAutoPushTargets(next);
      return { ...prev, targets: next };
    });
  }, [
    buildMetricTargets,
    mergeTargets,
    normalizePosition,
    scheduleAutoPushTargets,
    selectedTicker,
    state.active,
    vwap,
    agentBuyFinancial,
    agentBuyTotals,
    agentNames,
    agentSellFinancial,
    agentSellTotals,
    agentShortNames,
    selectedMetricIds,
    volumeProfile,
  ]);

  return {
    ...state,
    selectedMetricIds,
    setSelectedMetricIds,
    toggleMetric,
    openOverlay,
    closeOverlay,
    openOcrRoiPicker,
    clearOcrAnalysisRoi,
    setTargets,
    addPosition,
    removePosition,
    updatePosition,
  };
}
