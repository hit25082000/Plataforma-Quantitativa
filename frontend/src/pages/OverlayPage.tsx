import "../styles/overlayProfitTransparent.css";
import { METRIC_LINE_VP_GAP_PX, OVERLAY_VISUAL_FPS } from "../overlay/overlayConstants";
import { safeBuildOverlayFrame } from "../overlay/buildOverlayFrame";
import { overlayLineYCss } from "../overlay/chartGeom";
import { isMetricOcrOverlayLine } from "../overlay/filterMetricOverlayLines";
import { readOverlayDiagEnv } from "../overlay/overlayDiagEnv";
import { safeNumber, safePx } from "../overlay/safeStyle";
import type {
  OverlayAxisFitCanonical,
  OverlayAxisLabelSample,
  OverlayGeometryPayload,
  OverlayLayoutSnapshot,
  OverlayRenderFrame,
} from "../overlay/overlayFrameTypes";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { OCR_WS_URL, ocrWsUrlFromPort } from "../config/ocrPort";
import type {
  TapeIntelligenceLevel,
  TapeIntelligenceMessage,
  VolumeProfileMessage,
  VpOverlayDebugMessage,
  VpOverlayDisplay,
  VpOverlayMessage,
  WsBatchMessage,
  WsMessage,
  WsSingleMessage,
} from "../types/messages";
import { vpOverlayToTapeIntelligence, vpOverlayToVolumeProfile } from "../utils/vpOverlayAdapters";
import {
  type OcrAxisDeltasOrLegacy,
  overlayStatusColor,
  overlayStatusText,
} from "../utils/ocrStatus";
import { parseOverlayUpdatePayload } from "../utils/overlayUpdateCompat";
import { listenOcrOverlayStatus } from "../utils/ocrOverlayEvents";
import { isTauri } from "../utils/tauri";
import {
  PQ_CONFIG_SAVED_EVENT,
  PQ_OVERLAY_OCR_DEBUG_HUD_EVENT,
  PQ_PROFIT_OVERLAY_OCR_ERROR_EVENT,
  PQ_PROFIT_OVERLAY_OCR_FRAME_EVENT,
  type PqProfitOverlayOcrFramePayload,
  PQ_PROFIT_OVERLAY_OCR_READY_EVENT,
  PQ_PROFIT_OVERLAY_OCR_STARTING_EVENT,
  PQ_PROFIT_OVERLAY_VP_RELAY_EVENT,
  type PqProfitOverlayVpRelayPayload,
  type PqOverlayOcrDebugHudPayload,
} from "../constants/pqTauriEvents";

interface OverlayLine {
  value: number;
  y_screen: number;
  color: string;
  chart_left: number;
  chart_right: number;
  label?: string;
  status?: string;
  out_of_bounds?: boolean;
  line_id?: string;
}

interface ChartRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface DebugAxisLabel {
  value: number;
  y_screen: number;
}

interface DebugRegression {
  slope?: number | null;
  intercept?: number | null;
  value_per_px?: number | null;
}

interface DebugAnalysisRoi {
  left?: number | null;
  top?: number | null;
  width?: number | null;
  height?: number | null;
}

interface DebugChartBounds {
  left?: number | null;
  top?: number | null;
  right?: number | null;
  bottom?: number | null;
  width?: number | null;
  height?: number | null;
}

interface DebugVisualBlock {
  ocr_labels?: DebugAxisLabel[] | null;
  regression?: DebugRegression | null;
  analysis_roi?: DebugAnalysisRoi | null;
  chart_bounds?: DebugChartBounds | null;
  axis_samples?: unknown;
  axis_fit_canonical?: unknown;
}

interface OverlayData {
  lines: OverlayLine[];
  status: string;
  y_min: number | null;
  y_max: number | null;
  chart_rect?: ChartRect | null;
  geometry?: OverlayGeometryPayload | null;
  axis_fit?: OverlayAxisFitCanonical | null;
  axis_id?: number | null;
  axis_samples?: OverlayAxisLabelSample[] | null;
  axis_deltas?: OcrAxisDeltasOrLegacy | null;
  axis_diagnostics?: {
    raw_labels?: number;
    kept_labels?: number;
    rejected?: number;
    rejected_monotonic?: number;
    rejected_slope_outlier?: number;
  } | null;
  axis_status?: string | null;
  axis_source?: string | null;
  bad_frames?: number | null;
  axis_error_code?: string | null;
  axis_error_message?: string | null;
  last_good_axis_age_ms?: number | null;
  overlay_window_alive?: boolean | null;
  ocr_service_alive?: boolean | null;
  ocr_ws_connected?: boolean | null;
  vp_status?: string | null;
  debug_visual?: DebugVisualBlock | null;
  raw_axis_status?: string | null;
  normalized_axis_status?: string | null;
  parsed_labels_count?: number | null;
  ocr_confidence?: number | null;
  payload_seq?: number | null;
  ocr_pid?: number | null;
  ocr_port?: number | null;
  fallback_reason?: string | null;
  ws_url?: string | null;
  last_payload_age_ms?: number | null;
}

type OverlayOcrPhase =
  | "ocr_starting"
  | "ocr_connecting"
  | "ocr_warming"
  | "geometry_calibrating"
  | "axis_waiting"
  | "axis_stable"
  | "degraded";

const LABEL_W = 150;
const LABEL_H = 36;
const FONT = "'JetBrains Mono', 'Fira Mono', monospace";
/** Recuo à direita para não cobrir a faixa de botões/ferramentas do Profit. */
const DEFAULT_OVERLAY_RIGHT_MARGIN_PX = 208;
/** Desloca bloco de linha/label um pouco para a esquerda. */
const OVERLAY_LINE_LEFT_SHIFT_PX = 36;
const LABEL_MIN_GAP = LABEL_H + 4;
const LABEL_MARGIN_PX = 2;
const VP_WAITING_BADGE_W = 238;
const VP_WS_INITIAL_BACKOFF_MS = 500;
const VP_WS_MAX_BACKOFF_MS = 10_000;
const VP_DEMO_LOCK_MS = 30_000;
const VP_LAYOUT_UPDATE_MS = 500;
const PQ_LAST_OVERLAY_WINDOW_ERROR_KEY = "PQ_LAST_OVERLAY_WINDOW_ERROR";
const PQ_LAST_OVERLAY_PROMISE_ERROR_KEY = "PQ_LAST_OVERLAY_PROMISE_ERROR";

type AppConfigRead = {
  overlay_right_margin_px?: number | null;
  show_volume_profile_overlay?: boolean | null;
  show_tape_intelligence_overlay?: boolean | null;
  vp_fallback_mode?: string | null;
  vp_fallback_price_top?: number | null;
  vp_fallback_price_bot?: number | null;
  vp_overlay?: VpOverlayPrefsConfig | null;
  vp_period?: string | null;
};

interface PositionedOverlayLine extends OverlayLine {
  labelY: number;
  rank: number;
  dense: boolean;
}

interface ScaledChartRect extends ChartRect {
  right: number;
  bottom: number;
}

interface ScaledDebugVisual {
  labels: DebugAxisLabel[];
  regression: { slope: number; intercept: number; valuePerPx: number } | null;
  roi: ScaledChartRect | null;
  bounds: ScaledChartRect | null;
}

interface VolumeProfileRenderableLevel {
  price: number;
  y: number;
  width: number;
  totalVol: number;
  bidVol: number;
  askVol: number;
  isPoc: boolean;
  inValueArea: boolean;
}

interface VolumeProfileOverlayModel {
  chart: ScaledChartRect;
  profileLeft: number;
  profileRight: number;
  /** Extremo direito das linhas horizontais (VP / médias); pode esticar até à área do gráfico. */
  lineEndX: number;
  profileWidth: number;
  levelHeight: number;
  levels: VolumeProfileRenderableLevel[];
  pocY: number | null;
  vahY: number | null;
  valY: number | null;
  poc: number;
  vah: number;
  val: number;
  totalVol: number;
  period: VolumeProfileMessage["period"];
  ySource: "ocr" | "fallback";
  histogramCandidates: number;
  histogramRendered: number;
  histogramCoalesced: number;
}

interface TapeBadgeModel {
  key: "poc" | "val" | "vah";
  label: string;
  player: number;
  playerName?: string | null;
  side: "B" | "S" | "";
  y: number;
  x: number;
  color: string;
  top3: TapeIntelligenceLevel[];
}

function brokerDisplayName(id: number, name?: string | null): string {
  const n = (name ?? "").trim();
  if (n.length > 0 && !n.startsWith("#")) return n;
  if (/^#\d+$/.test(n)) return `ID:${id}`;
  if (n.startsWith("#")) {
    const rest = n.slice(1).trim();
    if (rest.length > 0) return `ID:${rest}`;
  }
  return `ID:${id}`;
}

function isSamePriceSet(a: OverlayLine[], b: OverlayLine[]): boolean {
  if (a.length !== b.length) return false;
  const aPairs = a.map((x) => `${x.label ?? ""}:${x.value}`).sort();
  const bPairs = b.map((x) => `${x.label ?? ""}:${x.value}`).sort();
  for (let i = 0; i < aPairs.length; i++) {
    if (aPairs[i] !== bPairs[i]) return false;
  }
  return true;
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const m = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[m - 1] + sorted[m]) / 2 : sorted[m];
}

function shouldRejectUnstableOcrFrame(
  prevLines: OverlayLine[],
  nextLines: OverlayLine[],
  axisDiagnostics: OverlayData["axis_diagnostics"],
): { reject: boolean; reason: string } {
  if (prevLines.length === 0 || nextLines.length === 0) {
    return { reject: false, reason: "no_prev_or_next_lines" };
  }
  if (!isSamePriceSet(prevLines, nextLines)) {
    return { reject: false, reason: "price_set_changed" };
  }
  const prevByKey = new Map(prevLines.map((l) => [`${l.label ?? ""}:${l.value}`, l.y_screen]));
  const deltas: number[] = [];
  for (const line of nextLines) {
    const key = `${line.label ?? ""}:${line.value}`;
    const prevY = prevByKey.get(key);
    if (typeof prevY !== "number") continue;
    deltas.push(Math.abs(line.y_screen - prevY));
  }
  if (deltas.length === 0) return { reject: false, reason: "no_delta_pairs" };
  const medianDelta = median(deltas);
  const kept = Number(axisDiagnostics?.kept_labels ?? 0);
  const rejected = Number(axisDiagnostics?.rejected ?? 0);
  const lowConfidence = kept <= 3 || rejected >= 2;
  const hasCollapsedToEdge = nextLines.filter((l) => l.y_screen <= 95 || l.y_screen >= 1075).length >= 2;
  const largeJump = medianDelta >= 80;
  if (lowConfidence && (largeJump || hasCollapsedToEdge)) {
    return { reject: true, reason: "low_confidence_large_jump_or_edge_collapse" };
  }
  return { reject: false, reason: "accepted" };
}

function shouldHoldPreviousLinesOnOcrDropout(
  prev: OverlayData,
  next: OverlayData,
): { hold: boolean; reason: string } {
  const prevCount = Array.isArray(prev.lines) ? prev.lines.length : 0;
  const nextCount = Array.isArray(next.lines) ? next.lines.length : 0;
  if (prevCount === 0 || nextCount > 0) return { hold: false, reason: "no_dropout" };
  const status = String(next.status ?? "");
  const kept = Number(next.axis_diagnostics?.kept_labels ?? 0);
  const rejected = Number(next.axis_diagnostics?.rejected ?? 0);
  const ocrTransient =
    status.startsWith("ocr_insufficient_labels") ||
    status === "warming_up" ||
    status === "connecting" ||
    status === "ocr_unreachable_retrying";
  if (ocrTransient || kept <= 1 || rejected >= 1) {
    return { hold: true, reason: "transient_ocr_dropout" };
  }
  return { hold: false, reason: "dropout_without_ocr_signal" };
}

type AxisCaptureSnapshot = {
  yMin: number;
  yMax: number;
  slope: number | null;
  intercept: number | null;
  axisStatus: string | null;
  labelMin: number | null;
  labelMax: number | null;
};

function axisCaptureFromOverlayData(data: OverlayData): AxisCaptureSnapshot | null {
  const yMin = data.y_min;
  const yMax = data.y_max;
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) return null;
  const fit = data.axis_fit;
  const samples = Array.isArray(data.axis_samples) ? data.axis_samples : [];
  let labelMin: number | null = null;
  let labelMax: number | null = null;
  for (const raw of samples) {
    const row = raw as { value?: unknown };
    const v = Number(row.value);
    if (!Number.isFinite(v)) continue;
    labelMin = labelMin == null ? v : Math.min(labelMin, v);
    labelMax = labelMax == null ? v : Math.max(labelMax, v);
  }
  return {
    yMin: Number(yMin),
    yMax: Number(yMax),
    slope: typeof fit?.slope === "number" && Number.isFinite(fit.slope) ? fit.slope : null,
    intercept:
      typeof fit?.intercept === "number" && Number.isFinite(fit.intercept) ? fit.intercept : null,
    axisStatus: data.raw_axis_status ?? data.axis_status ?? null,
    labelMin,
    labelMax,
  };
}

function formatAxisCaptureLine(prefix: string, snap: AxisCaptureSnapshot | null): string {
  if (!snap) return `${prefix}: —`;
  const y = `P ${Math.round(snap.yMin)}–${Math.round(snap.yMax)}`;
  const fit =
    snap.slope != null && snap.intercept != null
      ? ` | m=${snap.slope.toFixed(5)} b=${snap.intercept.toFixed(1)}`
      : "";
  const prices =
    snap.labelMin != null && snap.labelMax != null
      ? ` | preços ${snap.labelMin}–${snap.labelMax}`
      : "";
  const st = snap.axisStatus ? ` [${snap.axisStatus}]` : "";
  return `${prefix}: ${y}${fit}${prices}${st}`;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function marketWsUrl(path: "/ws/volume-profile" | "/ws/vp-overlay"): string {
  if (isTauri()) return `ws://127.0.0.1:8000${path}`;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}

function parseMarketWsPayload(raw: unknown): WsMessage | null {
  if (typeof raw !== "string") return null;
  try {
    return JSON.parse(raw) as WsMessage;
  } catch {
    return null;
  }
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function normalizeGeometryFromPayload(row: unknown): OverlayGeometryPayload | null {
  if (!row || typeof row !== "object" || Array.isArray(row)) return null;
  const r = row as Record<string, unknown>;
  const num = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
  };
  const rectXY = (key: string): OverlayGeometryPayload["overlay_rect_screen"] => {
    const b = r[key];
    if (!b || typeof b !== "object") return null;
    const o = b as Record<string, unknown>;
    const x = num(o.x ?? o.left);
    const y = num(o.y ?? o.top);
    const w = num(o.width);
    const h = num(o.height);
    if (![x, y, w, h].every(Number.isFinite) || w <= 0 || h <= 0) return null;
    return { x, y, width: w, height: h };
  };
  const chart = r.chart_rect_screen;
  let chart_rect_screen: OverlayGeometryPayload["chart_rect_screen"] = null;
  if (chart && typeof chart === "object") {
    const c = chart as Record<string, unknown>;
    const left = num(c.left);
    const top = num(c.top);
    const width = num(c.width);
    const height = num(c.height);
    if ([left, top, width, height].every(Number.isFinite) && width > 0 && height > 0) {
      chart_rect_screen = { left, top, width, height };
    }
  }
  const sf = num(r.scale_factor);
  const scale_factor = Number.isFinite(sf) && sf > 0 ? sf : 1;
  const sig = r.geometry_signature;
  const mon = r.monitor_id;
  return {
    capture_rect_screen: rectXY("capture_rect_screen") ?? undefined,
    chart_rect_screen,
    overlay_rect_screen: rectXY("overlay_rect_screen") ?? undefined,
    scale_factor,
    monitor_id: typeof mon === "string" ? mon : mon != null ? String(mon) : null,
    geometry_signature: typeof sig === "string" ? sig : undefined,
  };
}

function normalizeAxisFitFromPayload(row: unknown): OverlayAxisFitCanonical | null {
  if (!row || typeof row !== "object" || Array.isArray(row)) return null;
  const o = row as Record<string, unknown>;
  const slope = Number(o.slope);
  const intercept = Number(o.intercept);
  const price_ref = Number(o.price_ref);
  const axis_id = Number(o.axis_id);
  const labels_count = Number(o.labels_count);
  const avg_error_px = Number(o.avg_error_px);
  const max_error_px = Number(o.max_error_px);
  const model = typeof o.model === "string" ? o.model : "y_chart_linear_v1";
  if (
    !Number.isFinite(slope) ||
    !Number.isFinite(intercept) ||
    !Number.isFinite(price_ref) ||
    !Number.isFinite(axis_id)
  ) {
    return null;
  }
  return {
    axis_id,
    model,
    price_ref,
    slope,
    intercept,
    labels_count: Number.isFinite(labels_count) ? labels_count : 0,
    avg_error_px: Number.isFinite(avg_error_px) ? avg_error_px : 0,
    max_error_px: Number.isFinite(max_error_px) ? max_error_px : 0,
    created_at_ms: Number.isFinite(Number(o.created_at_ms)) ? Number(o.created_at_ms) : undefined,
    geometry_signature: typeof o.geometry_signature === "string" ? o.geometry_signature : undefined,
  };
}

function normalizeAxisSamplesFromPayload(raw: unknown): OverlayAxisLabelSample[] | null {
  if (!Array.isArray(raw)) return null;
  const out: OverlayAxisLabelSample[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const value = Number(o.value);
    const y_screen = Number(o.y_screen);
    if (!Number.isFinite(value) || !Number.isFinite(y_screen)) continue;
    const yc = Number(o.y_chart);
    const ycap = Number(o.y_capture);
    const yp = Number(o.y_predicted);
    const err = Number(o.error_px);
    out.push({
      value,
      y_screen,
      y_chart: Number.isFinite(yc) ? yc : undefined,
      y_capture: Number.isFinite(ycap) ? ycap : undefined,
      y_predicted: Number.isFinite(yp) ? yp : undefined,
      error_px: Number.isFinite(err) ? err : undefined,
    });
  }
  return out.length ? out : null;
}

function normalizeAxisStatus(value: unknown): string {
  const raw = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (!raw) return "unknown";
  if (raw === "stable") return "stable";
  if (raw === "frozen" || raw === "freeze" || raw === "locked" || raw === "paused") return "frozen";
  if (raw === "manual_locked") return "manual_locked";
  if (raw === "manual_stable") return "manual_locked";
  if (raw === "ocr_validated") return "stable";
  if (raw === "ocr_conflict") return "frozen";
  if (raw === "boot_from_cache") return "suspect";
  if (raw === "boot_from_cache_degraded") return "suspect";
  if (raw === "degraded") return "frozen";
  if (raw === "recalibrating") return "recalibrating";
  if (raw === "suspect") return "suspect";
  if (raw === "no_axis" || raw === "not_found" || raw === "missing") return "no_axis";
  if (raw === "geometry_mismatch" || raw === "geometry_calibrating") return "geometry_calibrating";
  return raw;
}

function overlayGeometryCanonicalReady(data: OverlayData): boolean {
  const g = data.geometry;
  if (!g?.chart_rect_screen || !g.overlay_rect_screen) return false;
  const sf = Number(g.scale_factor);
  return Number.isFinite(sf) && sf > 0;
}

function overlayAxisFitReady(data: OverlayData): boolean {
  const f = data.axis_fit;
  if (!f || typeof f.slope !== "number" || !Number.isFinite(f.slope)) return false;
  return true;
}

function isAxisUsableForOcr(data: OverlayData): { usable: boolean; reason: string } {
  const axisStatus = normalizeAxisStatus(data.normalized_axis_status ?? data.axis_status ?? "");
  if (axisStatus === "geometry_calibrating") {
    return { usable: false, reason: "geometry_mismatch" };
  }
  const hasStableStatus =
    axisStatus === "stable" ||
    axisStatus === "manual_locked" ||
    axisStatus === "ocr_validated";
  if (!hasStableStatus) return { usable: false, reason: `axis_status_${axisStatus}` };

  const ageIgnoresStalenessCap = axisStatus === "manual_locked";

  if (overlayGeometryCanonicalReady(data) && overlayAxisFitReady(data)) {
    const labelsCount = Number(data.parsed_labels_count ?? 0);
    if (labelsCount > 0 && labelsCount < 3) return { usable: false, reason: "parsed_labels_lt_3" };
    const age = Number(data.last_good_axis_age_ms ?? 0);
    if (!Number.isFinite(age)) return { usable: true, reason: "" };
    if (ageIgnoresStalenessCap) {
      if (age > 5000) return { usable: true, reason: "axis_age_frozen" };
      return { usable: true, reason: "" };
    }
    if (age > 15000) return { usable: false, reason: "axis_age_no_axis" };
    if (age > 5000) return { usable: true, reason: "axis_age_frozen" };
    return { usable: true, reason: "" };
  }

  const yMin = data.y_min;
  const yMax = data.y_max;
  const hasScreenRange =
    Number.isFinite(yMin) &&
    Number.isFinite(yMax) &&
    Math.abs(Number(yMax) - Number(yMin)) > 50;
  if (!hasScreenRange) return { usable: false, reason: "screen_range_invalid" };

  const labelsCount = Number(data.parsed_labels_count ?? 0);
  if (labelsCount > 0 && labelsCount < 3) return { usable: false, reason: "parsed_labels_lt_3" };

  const age = Number(data.last_good_axis_age_ms ?? 0);
  if (!Number.isFinite(age)) return { usable: true, reason: "" };
  if (ageIgnoresStalenessCap) {
    if (age > 5000) return { usable: true, reason: "axis_age_frozen" };
    return { usable: true, reason: "" };
  }
  if (age > 15000) return { usable: false, reason: "axis_age_no_axis" };
  if (age > 5000) return { usable: true, reason: "axis_age_frozen" };
  return { usable: true, reason: "" };
}

function overlayFrameLinesDigest(f: OverlayRenderFrame): string {
  if (f.positionedLines.length === 0) return "0";
  return f.positionedLines
    .slice(0, 16)
    .map((l) => `${l.value}:${Math.round(l.y_screen * 10)}`)
    .join(",");
}

function overlayFrameRenderDigest(f: OverlayRenderFrame | null): string {
  if (!f) return "";
  const vp = f.volumeProfileOverlay;
  const vN = vp && Array.isArray(vp.levels) ? vp.levels.length : 0;
  return [
    f.viewportWidth,
    f.viewportHeight,
    Math.round(f.renderScale * 1000),
    f.guardStatus,
    f.positionedLines.length,
    f.tapeBadges.length,
    vN,
    f.effectiveYMin ?? "",
    f.effectiveYMax ?? "",
    f.effectiveFallbackReason,
    f.usingOcrChart,
    overlayFrameLinesDigest(f),
  ].join("|");
}

function overlayVisualCommitDigest(
  f: OverlayRenderFrame | null,
  snap: OverlayLayoutSnapshot,
): string {
  return [
    overlayFrameRenderDigest(f),
    snap.data.status,
    snap.data.axis_status ?? "",
    snap.data.normalized_axis_status ?? "",
    snap.data.last_good_axis_age_ms ?? "",
  ].join("§");
}

function sameFrame(a: OverlayRenderFrame | null, b: OverlayRenderFrame | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  const itemsA =
    a.positionedLines.length + a.tapeBadges.length + (a.volumeProfileOverlay?.levels?.length ?? 0);
  const itemsB =
    b.positionedLines.length + b.tapeBadges.length + (b.volumeProfileOverlay?.levels?.length ?? 0);
  return (
    a.viewportWidth === b.viewportWidth &&
    a.viewportHeight === b.viewportHeight &&
    a.guardStatus === b.guardStatus &&
    itemsA === itemsB &&
    overlayFrameRenderDigest(a) === overlayFrameRenderDigest(b)
  );
}

function scaleChartRect(rect: ChartRect | null | undefined, scale: number): ScaledChartRect | null {
  if (
    !rect ||
    !isFiniteNumber(rect.left) ||
    !isFiniteNumber(rect.top) ||
    !isFiniteNumber(rect.width) ||
    !isFiniteNumber(rect.height) ||
    rect.width <= 0 ||
    rect.height <= 0
  ) {
    return null;
  }
  const left = rect.left * scale;
  const top = rect.top * scale;
  const width = rect.width * scale;
  const height = rect.height * scale;
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
  };
}

function toScaledRect(
  left: unknown,
  top: unknown,
  width: unknown,
  height: unknown,
  scale: number,
): ScaledChartRect | null {
  if (
    !isFiniteNumber(left) ||
    !isFiniteNumber(top) ||
    !isFiniteNumber(width) ||
    !isFiniteNumber(height) ||
    width <= 0 ||
    height <= 0
  ) {
    return null;
  }
  return scaleChartRect({ left, top, width, height }, scale);
}

function normalizeDebugVisual(
  debugVisual: DebugVisualBlock | null | undefined,
  renderScale: number,
): ScaledDebugVisual | null {
  if (!debugVisual || typeof debugVisual !== "object") return null;
  const labels = Array.isArray(debugVisual.ocr_labels)
    ? debugVisual.ocr_labels
        .filter((label): label is DebugAxisLabel => label != null && typeof label === "object")
        .map((label) => ({
          value: Number(label.value),
          y_screen: Number(label.y_screen) * renderScale,
        }))
        .filter((label) => Number.isFinite(label.value) && Number.isFinite(label.y_screen))
    : [];
  const slope = Number(debugVisual.regression?.slope);
  const intercept = Number(debugVisual.regression?.intercept);
  const valuePerPx = Number(debugVisual.regression?.value_per_px);
  const regression =
    Number.isFinite(slope) && Number.isFinite(intercept) && Number.isFinite(valuePerPx)
      ? { slope, intercept, valuePerPx }
      : null;
  const roi = toScaledRect(
    debugVisual.analysis_roi?.left,
    debugVisual.analysis_roi?.top,
    debugVisual.analysis_roi?.width,
    debugVisual.analysis_roi?.height,
    renderScale,
  );
  const bounds = toScaledRect(
    debugVisual.chart_bounds?.left,
    debugVisual.chart_bounds?.top,
    debugVisual.chart_bounds?.width,
    debugVisual.chart_bounds?.height,
    renderScale,
  );
  if (labels.length === 0 && !regression && !roi && !bounds) return null;
  return { labels, regression, roi, bounds };
}

function priceToChartY(
  price: number,
  chart: ScaledChartRect,
  yMin: number | null,
  yMax: number | null,
): number | null {
  if (!isFiniteNumber(price) || !isFiniteNumber(yMin) || !isFiniteNumber(yMax)) {
    return null;
  }
  if (yMin === yMax || price < yMin || price > yMax) return null;
  const t = (yMax - price) / (yMax - yMin);
  return chart.top + clamp(t, 0, 1) * chart.height;
}

function alignmentDeltaPx(
  explicitY: number | undefined,
  price: number,
  chart: ScaledChartRect | null,
  renderScale: number,
  yMin: number | null,
  yMax: number | null,
): number | null {
  if (!chart) return null;
  const expected = priceToChartY(price, chart, yMin, yMax);
  const actual = isFiniteNumber(explicitY) ? explicitY * renderScale : expected;
  if (!isFiniteNumber(expected) || !isFiniteNumber(actual)) return null;
  return Math.abs(actual - expected);
}

function volumeProfilePriceRange(
  volumeProfile: VolumeProfileMessage | null,
): { min: number; max: number } | null {
  if (!volumeProfile || !Array.isArray(volumeProfile.levels)) return null;
  const prices = volumeProfile.levels
    .map((level) => Number(level.price))
    .filter((price) => Number.isFinite(price));
  if (prices.length === 0) return null;
  const av = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
  };
  const anchors = [av(volumeProfile.poc), av(volumeProfile.vah), av(volumeProfile.val)].filter((n) =>
    Number.isFinite(n),
  );
  let min = Math.min(...prices, ...(anchors.length ? anchors : prices));
  let max = Math.max(...prices, ...(anchors.length ? anchors : prices));
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = Math.max(Math.abs(max - min) * 0.06, Math.abs(volumeProfile.price_step || 1));
  return { min: min - pad, max: max + pad };
}

function fallbackChartRectForVp(width: number, height: number): ScaledChartRect | null {
  if (width < 320 || height < 260) return null;
  const left = 18;
  const top = 44;
  const right = Math.max(left + 320, width - 22);
  const bottom = Math.max(top + 220, height - 58);
  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
    right,
    bottom,
  };
}

function formatCompactVol(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return Math.round(v).toLocaleString("pt-BR");
}

function formatProfilePrice(v: number): string {
  return v >= 1000
    ? v.toLocaleString("pt-BR", { maximumFractionDigits: 0 })
    : v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function volumeProfileLevelColor(level: VolumeProfileRenderableLevel, poc: number): string {
  const pocF = safeNumber(poc, safeNumber(level.price, 0));
  if (level.isPoc) return "rgba(245,158,11,0.96)";
  if (level.price >= pocF) {
    return level.inValueArea ? "rgba(239,68,68,0.84)" : "rgba(239,68,68,0.52)";
  }
  return level.inValueArea ? "rgba(168,85,247,0.82)" : "rgba(168,85,247,0.48)";
}

function isDemoPayload(msg: VolumeProfileMessage | TapeIntelligenceMessage): boolean {
  return (msg as { demo?: boolean }).demo === true;
}

/** Alinhado a `VpOverlayPrefs` (Tauri) e `display` no WS (`vp_overlay`). */
interface VpOverlayPrefsConfig {
  enabled?: boolean;
  poc_visible?: boolean;
  val_vah_visible?: boolean;
  labels_visible?: boolean;
  histogram_visible?: boolean;
  top_avg_visible?: boolean;
  stretch_lines?: boolean;
  max_avg_lines?: number;
  max_visible_histogram_levels?: number;
}

function mergeVpOverlayDisplay(
  server: VpOverlayDisplay | null,
  prefs: VpOverlayPrefsConfig | null,
): VpOverlayDisplay {
  const out: VpOverlayDisplay =
    server && typeof server === "object" ? { ...server } : {};
  if (!prefs) return out;
  if (prefs.enabled !== undefined) out.overlay_enabled = prefs.enabled;
  if (prefs.poc_visible !== undefined) out.poc_visible = prefs.poc_visible;
  if (prefs.val_vah_visible !== undefined) out.val_vah_visible = prefs.val_vah_visible;
  if (prefs.labels_visible !== undefined) out.labels_visible = prefs.labels_visible;
  if (prefs.histogram_visible !== undefined) out.histogram_visible = prefs.histogram_visible;
  if (prefs.top_avg_visible !== undefined) out.top_avg_visible = prefs.top_avg_visible;
  if (prefs.stretch_lines !== undefined) out.stretch_lines = prefs.stretch_lines;
  if (prefs.max_avg_lines !== undefined) out.max_avg_lines = prefs.max_avg_lines;
  if (prefs.max_visible_histogram_levels !== undefined) {
    out.max_visible_histogram_levels = prefs.max_visible_histogram_levels;
  }
  return out;
}

function countDenseLabelCollisions(lines: OverlayLine[]): number {
  if (lines.length < 2) return 0;
  const sorted = [...lines].sort((a, b) => a.y_screen - b.y_screen);
  let c = 0;
  for (let i = 1; i < sorted.length; i++) {
    if (Math.abs(sorted[i].y_screen - sorted[i - 1].y_screen) < LABEL_MIN_GAP) c += 1;
  }
  return c;
}

function applyVpTapePayload(
  item: WsSingleMessage,
  onVolumeProfile: (msg: VolumeProfileMessage) => void,
  onTapeIntelligence: (msg: TapeIntelligenceMessage) => void,
): void {
  if (item.topic !== "market") return;
  const t = (item as { type?: string }).type;
  if (t === "volume_profile") {
    onVolumeProfile(item as VolumeProfileMessage);
  } else if (t === "tape_intelligence") {
    onTapeIntelligence(item as TapeIntelligenceMessage);
  }
}

function applyVpTapeWsData(
  raw: unknown,
  onVolumeProfile: (msg: VolumeProfileMessage) => void,
  onTapeIntelligence: (msg: TapeIntelligenceMessage) => void,
): void {
  if (typeof raw !== "string") return;
  const parsed = JSON.parse(raw) as WsMessage;
  if (parsed.topic === "ws_batch") {
    for (const item of (parsed as WsBatchMessage).items) {
      applyVpTapePayload(item, onVolumeProfile, onTapeIntelligence);
    }
    return;
  }
  applyVpTapePayload(parsed as WsSingleMessage, onVolumeProfile, onTapeIntelligence);
}

function layoutOverlayLines(lines: OverlayLine[], screenH: number): PositionedOverlayLine[] {
  if (lines.length === 0) return [];

  const sortedByY = lines
    .map((line, index) => ({ line, index }))
    .sort((a, b) => a.line.y_screen - b.line.y_screen);

  const gaps: number[] = [];
  for (let i = 1; i < sortedByY.length; i++) {
    gaps.push(Math.abs(sortedByY[i].line.y_screen - sortedByY[i - 1].line.y_screen));
  }
  const avgGap = gaps.length > 0 ? gaps.reduce((acc, g) => acc + g, 0) / gaps.length : LABEL_MIN_GAP;
  const dense = sortedByY.length >= 4 || avgGap < LABEL_MIN_GAP + 8;

  const minCenter = LABEL_H / 2 + LABEL_MARGIN_PX;
  const maxCenter = screenH - LABEL_H / 2 - LABEL_MARGIN_PX;
  const centers = sortedByY.map((x) => clamp(x.line.y_screen, minCenter, maxCenter));

  // Passo para baixo: garante distanciamento mínimo entre labels.
  for (let i = 1; i < centers.length; i++) {
    centers[i] = Math.max(centers[i], centers[i - 1] + LABEL_MIN_GAP);
  }

  const overflowBottom = centers[centers.length - 1] - maxCenter;
  if (overflowBottom > 0) {
    for (let i = 0; i < centers.length; i++) centers[i] -= overflowBottom;
  }

  // Passo para cima: corrige colisões restantes após ajustar o rodapé.
  for (let i = centers.length - 2; i >= 0; i--) {
    centers[i] = Math.min(centers[i], centers[i + 1] - LABEL_MIN_GAP);
  }

  const overflowTop = minCenter - centers[0];
  if (overflowTop > 0) {
    for (let i = 0; i < centers.length; i++) centers[i] += overflowTop;
  }

  const arranged = sortedByY.map((x, i) => ({
    line: x.line,
    index: x.index,
    labelY: clamp(centers[i], minCenter, maxCenter),
    rank: i + 1,
    dense,
  }));

  const byOriginal = new Array<PositionedOverlayLine>(arranged.length);
  for (const item of arranged) {
    byOriginal[item.index] = {
      ...item.line,
      labelY: item.labelY,
      rank: item.rank,
      dense: item.dense,
    };
  }
  return byOriginal;
}

type CanonicalLineStatus = "stable" | "frozen" | "out_of_bounds" | "hidden" | "unknown";

function canonicalizeLineStatus(
  status: string | undefined,
  outOfBounds: boolean | undefined,
): CanonicalLineStatus {
  if (outOfBounds === true) return "out_of_bounds";
  const raw = String(status ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  if (!raw) return "stable";
  if (
    raw === "stable" ||
    raw === "ok" ||
    raw === "active" ||
    raw === "tracked" ||
    raw === "visible" ||
    raw === "in_bounds"
  ) {
    return "stable";
  }
  if (raw === "frozen" || raw === "freeze" || raw === "locked" || raw === "paused") {
    return "frozen";
  }
  if (
    raw === "out_of_bounds" ||
    raw === "oob" ||
    raw === "outside" ||
    raw === "outside_chart" ||
    raw === "clipped"
  ) {
    return "out_of_bounds";
  }
  if (raw === "hidden" || raw === "suppressed" || raw === "filtered" || raw === "disabled") {
    return "hidden";
  }
  return "unknown";
}

export default function OverlayPage() {
  const [data, setData] = useState<OverlayData>({
    lines: [],
    status: "connecting",
    y_min: null,
    y_max: null,
    chart_rect: null,
    geometry: null,
    axis_fit: null,
    axis_id: null,
    axis_samples: null,
    axis_deltas: null,
    axis_diagnostics: null,
  });
  const [volumeProfile, setVolumeProfile] = useState<VolumeProfileMessage | null>(null);
  const [tapeIntelligence, setTapeIntelligence] = useState<TapeIntelligenceMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const vpWsRef = useRef<WebSocket | null>(null);
  const demoLockUntilRef = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();
  const vpRetryTimer = useRef<ReturnType<typeof setTimeout>>();
  const wsRetryRef = useRef(0);
  const vpWsBackoffRef = useRef(VP_WS_INITIAL_BACKOFF_MS);
  const wsStartRef = useRef<number | null>(null);
  const wsOpenLoggedRef = useRef(false);
  const ocrRelayConnectedRef = useRef(false);
  const handleOcrPayloadRef = useRef<(raw: string, wsUrlForState: string | null) => void>(() => {});
  const ocrSessionWsUrlRef = useRef<string>(OCR_WS_URL);
  const firstAxisStableLoggedRef = useRef(false);
  const firstLinesRenderedLoggedRef = useRef(false);
  const [startupEventState, setStartupEventState] = useState<"idle" | "starting" | "ready" | "error">(
    "idle",
  );
  const [axisCaptureInitial, setAxisCaptureInitial] = useState<AxisCaptureSnapshot | null>(null);
  const [axisCaptureCurrent, setAxisCaptureCurrent] = useState<AxisCaptureSnapshot | null>(null);
  const [overlayRightMarginPx, setOverlayRightMarginPx] = useState<number>(
    DEFAULT_OVERLAY_RIGHT_MARGIN_PX,
  );
  const [showVolumeProfileOverlay, setShowVolumeProfileOverlay] = useState(true);
  const [showTapeIntelligenceOverlay, setShowTapeIntelligenceOverlay] = useState(true);
  const [vpFallbackMode, setVpFallbackMode] = useState("auto");
  const [vpFallbackPriceTop, setVpFallbackPriceTop] = useState<number | null>(null);
  const [vpFallbackPriceBot, setVpFallbackPriceBot] = useState<number | null>(null);
  const [fallbackYLock, setFallbackYLock] = useState<{ min: number; max: number } | null>(null);
  const lastVpTickerRef = useRef<string | undefined>(undefined);
  const overlayHeartbeatRef = useRef<Record<string, unknown>>({});
  const snapshotDraftRef = useRef<OverlayLayoutSnapshot | null>(null);
  const lastGoodSvgFrameRef = useRef<OverlayRenderFrame | null>(null);
  const displayedSvgFrameRef = useRef<OverlayRenderFrame | null>(null);
  const lastRenderErrRef = useRef<string | null>(null);
  const [viewport, setViewport] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
    dpr: window.devicePixelRatio || 1,
  });
  const [svgRafNonce, setSvgRafNonce] = useState(0);
  const vpOverlayPrimaryRef = useRef(false);
  const vpOvWsRef = useRef<WebSocket | null>(null);
  const vpOvBackoffRef = useRef(VP_WS_INITIAL_BACKOFF_MS);
  const vpOvRetryTimer = useRef<ReturnType<typeof setTimeout>>();
  const [vpOverlayDisplay, setVpOverlayDisplay] = useState<VpOverlayDisplay | null>(null);
  const [vpOverlayPrefs, setVpOverlayPrefs] = useState<VpOverlayPrefsConfig | null>(null);
  const [vpOverlayHealth, setVpOverlayHealth] = useState<VpOverlayDebugMessage["health"] | null>(null);
  const [vpOverlayRawTicker, setVpOverlayRawTicker] = useState<string | null>(null);
  const [vpOverlayAgeMs, setVpOverlayAgeMs] = useState<number | null>(null);
  const [vpPeriodCfg, setVpPeriodCfg] = useState<"day" | "week" | "manual">("day");
  const [overlayCommitMs, setOverlayCommitMs] = useState(0);
  const [overlayCommitHz, setOverlayCommitHz] = useState(0);
  const [showVisualDebug, setShowVisualDebug] = useState(false);
  const [debugLayerVisibility, setDebugLayerVisibility] = useState({
    ocrLabels: true,
    regression: true,
    roi: true,
    bounds: true,
  });
  const [manualCalibrateMode, setManualCalibrateMode] = useState(false);
  const [ocrHudCollapsed, setOcrHudCollapsed] = useState(true);
  const [manualPointA, setManualPointA] = useState<{ y: number; value: string } | null>(null);
  const [manualPointB, setManualPointB] = useState<{ y: number; value: string } | null>(null);
  const [manualCalibrateHint, setManualCalibrateHint] = useState<string | null>(null);
  const [ocrWsUrl, setOcrWsUrl] = useState<string | null>(null);
  const [lastPayloadAtMs, setLastPayloadAtMs] = useState<number | null>(null);
  const overlayPerfLastRef = useRef(performance.now());
  const overlayPerfBootRef = useRef(true);
  const lastSvgVisualDigestRef = useRef<string | null>(null);
  const rafLastPushedFrameRef = useRef<OverlayRenderFrame | null>(null);
  const frozenByNoAxisRef = useRef(false);
  const vpCommitAtRef = useRef(0);
  const tapeCommitAtRef = useRef(0);
  const pendingVpRef = useRef<VolumeProfileMessage | null>(null);
  const pendingTapeRef = useRef<TapeIntelligenceMessage | null>(null);
  const vpFlushTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const tapeFlushTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const effectiveVpDisplay = useMemo(
    () => mergeVpOverlayDisplay(vpOverlayDisplay, vpOverlayPrefs),
    [vpOverlayDisplay, vpOverlayPrefs],
  );

  const scheduleVolumeProfileCommit = useCallback((msg: VolumeProfileMessage) => {
    const now = Date.now();
    const elapsed = now - vpCommitAtRef.current;
    if (elapsed >= VP_LAYOUT_UPDATE_MS) {
      vpCommitAtRef.current = now;
      pendingVpRef.current = null;
      if (vpFlushTimerRef.current) {
        clearTimeout(vpFlushTimerRef.current);
        vpFlushTimerRef.current = undefined;
      }
      setVolumeProfile(msg);
      return;
    }
    pendingVpRef.current = msg;
    if (vpFlushTimerRef.current) return;
    vpFlushTimerRef.current = setTimeout(() => {
      vpFlushTimerRef.current = undefined;
      const pending = pendingVpRef.current;
      if (!pending) return;
      pendingVpRef.current = null;
      vpCommitAtRef.current = Date.now();
      setVolumeProfile(pending);
    }, Math.max(0, VP_LAYOUT_UPDATE_MS - elapsed));
  }, []);

  const scheduleTapeIntelligenceCommit = useCallback((msg: TapeIntelligenceMessage) => {
    const now = Date.now();
    const elapsed = now - tapeCommitAtRef.current;
    if (elapsed >= VP_LAYOUT_UPDATE_MS) {
      tapeCommitAtRef.current = now;
      pendingTapeRef.current = null;
      if (tapeFlushTimerRef.current) {
        clearTimeout(tapeFlushTimerRef.current);
        tapeFlushTimerRef.current = undefined;
      }
      setTapeIntelligence(msg);
      return;
    }
    pendingTapeRef.current = msg;
    if (tapeFlushTimerRef.current) return;
    tapeFlushTimerRef.current = setTimeout(() => {
      tapeFlushTimerRef.current = undefined;
      const pending = pendingTapeRef.current;
      if (!pending) return;
      pendingTapeRef.current = null;
      tapeCommitAtRef.current = Date.now();
      setTapeIntelligence(pending);
    }, Math.max(0, VP_LAYOUT_UPDATE_MS - elapsed));
  }, []);

  const patchVpOverlayPref = useCallback((patch: Partial<VpOverlayPrefsConfig>) => {
    setVpOverlayPrefs((prev) => ({ ...(prev ?? {}), ...patch }));
    if (isTauri()) {
      void invoke("write_config", { config: { vp_overlay: patch } });
    }
  }, []);

  const setVpPeriod = useCallback((period: "day" | "week" | "manual") => {
    setVpPeriodCfg(period);
    if (!isTauri()) return;
    void invoke<{ success?: boolean; message?: string }>("set_vp_period", { period }).catch(() => {});
  }, []);

  const [recalibrateHint, setRecalibrateHint] = useState<string | null>(null);
  const [axisActionHint, setAxisActionHint] = useState<string | null>(null);
  const recalibrateOcr = useCallback(() => {
    if (!isTauri()) return;
    void invoke<{ ok?: boolean; message?: string }>("recalibrate_profit_ocr")
      .then((r) => setRecalibrateHint(r?.message ?? "ok"))
      .catch((e) =>
        setRecalibrateHint(e instanceof Error ? e.message : String(e ?? "erro")),
      );
    window.setTimeout(() => setRecalibrateHint(null), 5000);
  }, []);
  const freezeOcrAxis = useCallback(() => {
    if (!isTauri()) return;
    void invoke<{ ok?: boolean; message?: string }>("freeze_profit_ocr")
      .then((r) => setAxisActionHint(r?.message ?? "ok"))
      .catch((e) => setAxisActionHint(e instanceof Error ? e.message : String(e ?? "erro")));
    window.setTimeout(() => setAxisActionHint(null), 5000);
  }, []);
  const unfreezeOcrAxis = useCallback(() => {
    if (!isTauri()) return;
    void invoke<{ ok?: boolean; message?: string }>("unfreeze_profit_ocr")
      .then((r) => setAxisActionHint(r?.message ?? "ok"))
      .catch((e) => setAxisActionHint(e instanceof Error ? e.message : String(e ?? "erro")));
    window.setTimeout(() => setAxisActionHint(null), 5000);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void listenOcrOverlayStatus((payload) => {
      if (cancelled) return;
      if (payload.action === "startup") {
        if (payload.status === "start") setStartupEventState("starting");
        else if (payload.status === "ok") setStartupEventState("ready");
        else if (payload.status === "error") setStartupEventState("error");
        return;
      }
      if (payload.action === "recalibrate") {
        if (payload.status === "start") setRecalibrateHint("recalibrando...");
        else if (payload.status === "ok") setRecalibrateHint("recalibrado");
        else if (payload.status === "error") {
          const code = payload.details?.http_status;
          setRecalibrateHint(
            typeof code === "number" ? `falha recalibração (HTTP ${code})` : "falha recalibração",
          );
        }
        window.setTimeout(() => setRecalibrateHint(null), 5000);
        return;
      }
      if (payload.action === "freeze") {
        if (payload.status === "start") setAxisActionHint("congelando eixo...");
        else if (payload.status === "released") setAxisActionHint("descongelando eixo...");
        else if (payload.status === "ok") {
          const phase = payload.details?.phase;
          setAxisActionHint(phase === "unfreeze" ? "eixo descongelado" : "eixo congelado");
        } else if (payload.status === "error") {
          const code = payload.details?.http_status;
          setAxisActionHint(typeof code === "number" ? `falha eixo (HTTP ${code})` : "falha eixo");
        }
        window.setTimeout(() => setAxisActionHint(null), 5000);
      }
    }).then((fn) => {
      if (cancelled) {
        fn();
        return;
      }
      unlisten = fn;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    void invoke<number>("get_ocr_runtime_port")
      .then((port) => {
        if (Number.isFinite(port) && port > 0) {
          setStartupEventState((prev) =>
            prev === "idle" || prev === "starting" ? "ready" : prev,
          );
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    const unlisten: Array<() => void> = [];
    void (async () => {
      const onStarting = await listen(PQ_PROFIT_OVERLAY_OCR_STARTING_EVENT, () => {
        if (!cancelled) setStartupEventState("starting");
      });
      const onReady = await listen(PQ_PROFIT_OVERLAY_OCR_READY_EVENT, () => {
        if (!cancelled) {
          setStartupEventState("ready");
          void invoke("push_profit_overlay_rect_to_ocr").catch(() => {});
        }
      });
      const onError = await listen(PQ_PROFIT_OVERLAY_OCR_ERROR_EVENT, () => {
        if (!cancelled) setStartupEventState("error");
      });
      if (cancelled) {
        onStarting();
        onReady();
        onError();
        return;
      }
      unlisten.push(onStarting, onReady, onError);
    })();
    return () => {
      cancelled = true;
      for (const fn of unlisten) fn();
    };
  }, []);

  const applyOverlayConfigFromTauri = useCallback((cfg: AppConfigRead) => {
    const v = cfg?.overlay_right_margin_px;
    if (typeof v === "number" && Number.isFinite(v) && v >= 0) {
      setOverlayRightMarginPx(v);
    }
    if (typeof cfg?.show_volume_profile_overlay === "boolean") {
      setShowVolumeProfileOverlay(cfg.show_volume_profile_overlay);
    }
    if (typeof cfg?.show_tape_intelligence_overlay === "boolean") {
      setShowTapeIntelligenceOverlay(cfg.show_tape_intelligence_overlay);
    }
    const fm = (cfg.vp_fallback_mode ?? "auto").trim().toLowerCase();
    setVpFallbackMode(fm === "manual" ? "manual" : "auto");
    setVpFallbackPriceTop(
      typeof cfg.vp_fallback_price_top === "number" && Number.isFinite(cfg.vp_fallback_price_top)
        ? cfg.vp_fallback_price_top
        : null,
    );
    setVpFallbackPriceBot(
      typeof cfg.vp_fallback_price_bot === "number" && Number.isFinite(cfg.vp_fallback_price_bot)
        ? cfg.vp_fallback_price_bot
        : null,
    );
    if (cfg.vp_overlay != null && typeof cfg.vp_overlay === "object") {
      setVpOverlayPrefs(cfg.vp_overlay);
    }
    const p = (cfg.vp_period ?? "day").trim().toLowerCase();
    if (p === "week" || p === "manual") setVpPeriodCfg(p);
    else setVpPeriodCfg("day");
  }, []);

  const applyVolumeProfileMessage = useCallback((msg: VolumeProfileMessage) => {
    const now = Date.now();
    if (isDemoPayload(msg)) {
      demoLockUntilRef.current = now + VP_DEMO_LOCK_MS;
    } else if (demoLockUntilRef.current > now) {
      return;
    }
    scheduleVolumeProfileCommit(msg);
  }, [scheduleVolumeProfileCommit]);

  const applyTapeIntelligenceMessage = useCallback((msg: TapeIntelligenceMessage) => {
    const now = Date.now();
    if (isDemoPayload(msg)) {
      demoLockUntilRef.current = now + VP_DEMO_LOCK_MS;
    } else if (demoLockUntilRef.current > now) {
      return;
    }
    scheduleTapeIntelligenceCommit(msg);
  }, [scheduleTapeIntelligenceCommit]);

  const ingestVpOverlayMessage = useCallback((msg: VpOverlayMessage) => {
    const now = Date.now();
    if (msg.demo === true) {
      demoLockUntilRef.current = now + VP_DEMO_LOCK_MS;
    } else if (demoLockUntilRef.current > now) {
      return;
    }
    vpOverlayPrimaryRef.current = true;
    setVpOverlayRawTicker(typeof msg.raw_ticker === "string" && msg.raw_ticker.trim() ? msg.raw_ticker : null);
    const updatedAt = Number(msg.updated_at);
    if (Number.isFinite(updatedAt) && updatedAt > 0) {
      const normalized = updatedAt < 1e12 ? updatedAt * 1000 : updatedAt;
      setVpOverlayAgeMs(Math.max(0, Date.now() - normalized));
    } else {
      setVpOverlayAgeMs(null);
    }
    const d = msg.display;
    setVpOverlayDisplay((prev) =>
      d && typeof d === "object" ? (d as VpOverlayDisplay) : prev,
    );
    const h = msg.health;
    setVpOverlayHealth(h && typeof h === "object" ? (h as VpOverlayDebugMessage["health"]) : null);
    scheduleVolumeProfileCommit(vpOverlayToVolumeProfile(msg));
    scheduleTapeIntelligenceCommit(vpOverlayToTapeIntelligence(msg));
  }, [scheduleTapeIntelligenceCommit, scheduleVolumeProfileCommit]);

  useEffect(() => {
    return () => {
      if (vpFlushTimerRef.current) clearTimeout(vpFlushTimerRef.current);
      if (tapeFlushTimerRef.current) clearTimeout(tapeFlushTimerRef.current);
      pendingVpRef.current = null;
      pendingTapeRef.current = null;
    };
  }, []);

  const processOcrPayload = useCallback((raw: string, wsUrlForState: string | null) => {
    const resolvedWs =
      typeof wsUrlForState === "string" && wsUrlForState.trim().length > 0
        ? wsUrlForState.trim()
        : ocrSessionWsUrlRef.current;
    setOcrWsUrl(resolvedWs);
    ocrRelayConnectedRef.current = true;
    try {
      const msg = JSON.parse(raw);
      const parsed = parseOverlayUpdatePayload(msg);
      if (parsed) {
        setLastPayloadAtMs(Date.now());
        setStartupEventState((prev) =>
          prev === "starting" || prev === "idle" ? "ready" : prev,
        );
        const lines = parsed.lines;
        setData((prev) => {
          const next = {
            ...parsed.rawData,
            status: parsed.status || prev.status,
            lines,
            y_min: parsed.yMin ?? prev.y_min,
            y_max: parsed.yMax ?? prev.y_max,
            axis_deltas: parsed.axisDeltas ?? prev.axis_deltas,
            axis_diagnostics: parsed.axisDiagnostics ?? prev.axis_diagnostics,
            axis_status: parsed.axisStatus ?? prev.axis_status,
            axis_source: parsed.axisSource ?? prev.axis_source,
            bad_frames: parsed.badFrames ?? prev.bad_frames,
            axis_error_code: parsed.axisErrorCode ?? prev.axis_error_code,
            axis_error_message: parsed.axisErrorMessage ?? prev.axis_error_message,
            last_good_axis_age_ms: parsed.lastGoodAxisAgeMs ?? prev.last_good_axis_age_ms,
            overlay_window_alive: parsed.overlayWindowAlive ?? prev.overlay_window_alive,
            ocr_service_alive: parsed.ocrServiceAlive ?? prev.ocr_service_alive,
            ocr_ws_connected: parsed.ocrWsConnected ?? prev.ocr_ws_connected,
            vp_status: parsed.vpStatus ?? prev.vp_status,
            debug_visual: parsed.debugVisual ?? prev.debug_visual ?? null,
            raw_axis_status: parsed.axisStatus ?? prev.raw_axis_status ?? null,
            normalized_axis_status: parsed.normalizedAxisStatus ?? prev.normalized_axis_status ?? null,
            parsed_labels_count: parsed.parsedLabelsCount ?? prev.parsed_labels_count ?? null,
            ocr_confidence: parsed.ocrConfidence ?? prev.ocr_confidence ?? null,
            payload_seq: parsed.payloadSeq ?? prev.payload_seq ?? null,
            ocr_pid: parsed.ocrPid ?? prev.ocr_pid ?? null,
            ocr_port: parsed.ocrPort ?? prev.ocr_port ?? null,
            geometry: normalizeGeometryFromPayload(parsed.geometry) ?? prev.geometry ?? null,
            axis_fit: normalizeAxisFitFromPayload(parsed.axisFit) ?? prev.axis_fit ?? null,
            axis_id: parsed.axisId ?? prev.axis_id ?? null,
            axis_samples:
              normalizeAxisSamplesFromPayload(parsed.axisSamples) ??
              normalizeAxisSamplesFromPayload(
                parsed.debugVisual && typeof parsed.debugVisual === "object"
                  ? (parsed.debugVisual as { axis_samples?: unknown }).axis_samples
                  : null,
              ) ??
              prev.axis_samples ??
              null,
            ws_url: resolvedWs,
            last_payload_age_ms: 0,
          } as OverlayData;
          const holdVerdict = shouldHoldPreviousLinesOnOcrDropout(prev, next);
          const rejectVerdict = shouldRejectUnstableOcrFrame(
            prev.lines,
            next.lines,
            next.axis_diagnostics,
          );
          if (rejectVerdict.reject) {
            return {
              ...prev,
              status: prev.status || next.status,
              bad_frames: next.bad_frames ?? prev.bad_frames,
              axis_status: next.axis_status ?? prev.axis_status,
              axis_source: next.axis_source ?? prev.axis_source,
              axis_error_code: next.axis_error_code ?? prev.axis_error_code,
              axis_error_message: next.axis_error_message ?? prev.axis_error_message,
              last_good_axis_age_ms: next.last_good_axis_age_ms ?? prev.last_good_axis_age_ms,
            };
          }
          if (holdVerdict.hold) {
            return {
              ...next,
              lines: prev.lines,
            };
          }
          const merged = next;
          const cap = axisCaptureFromOverlayData(merged);
          if (cap) {
            setAxisCaptureCurrent(cap);
            setAxisCaptureInitial((prevIni) => prevIni ?? cap);
          }
          return merged;
        });
      }
    } catch {
      // ignore parse errors
    }
  }, []);

  useLayoutEffect(() => {
    handleOcrPayloadRef.current = processOcrPayload;
  }, [processOcrPayload]);

  const connect = useCallback(() => {
    if (isTauri()) {
      return;
    }
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }
    setData((prev) => ({ ...prev, status: "ocr_connecting" }));
    if (wsStartRef.current == null) wsStartRef.current = performance.now();
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
      setOcrWsUrl(wsUrl);
      ocrSessionWsUrlRef.current = wsUrl;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        wsRetryRef.current = 0;
        if (!wsOpenLoggedRef.current && wsStartRef.current != null) {
          const ms = Math.round(performance.now() - wsStartRef.current);
          console.info(`[overlay-metric] ws_ocr_open_ms=${ms}`);
          wsOpenLoggedRef.current = true;
        }
        setData((prev) => ({ ...prev, status: "ocr_connecting" }));
      };

      ws.onmessage = (ev) => {
        handleOcrPayloadRef.current(String(ev.data ?? ""), null);
      };

      ws.onclose = () => {
        const delays = [
          250, 500, 800, 1200, 1600, 2000, 2500, 3000, 3500, 4000, 4500,
        ];
        const i = Math.min(wsRetryRef.current++, delays.length - 1);
        const ms = (delays[i] ?? 4500) + Math.floor(Math.random() * 120);
        setData((prev) => ({
          ...prev,
          status: wsRetryRef.current > 32 ? "degraded" : "ocr_warming",
        }));
        retryTimer.current = setTimeout(connect, ms);
      };

      ws.onerror = () => ws.close();
    };
    void openWs();
  }, []);

  useEffect(() => {
    if (isTauri()) {
      void (async () => {
        await Promise.race([
          invoke("prewarm_profit_ocr").catch(() => {}),
          new Promise<void>((r) => {
            window.setTimeout(r, 15_000);
          }),
        ]);
      })();
      return () => {};
    }
    connect();
    return () => {
      wsRef.current?.close();
      clearTimeout(retryTimer.current);
    };
  }, [connect]);

  useEffect(() => {
    if (!isTauri()) return;
    let mounted = true;
    let unlisten: (() => void) | undefined;
    void listen<PqProfitOverlayOcrFramePayload>(
      PQ_PROFIT_OVERLAY_OCR_FRAME_EVENT,
      (ev) => {
        if (!mounted) return;
        const pl = ev.payload;
        if (!pl || typeof pl.data !== "string") return;
        handleOcrPayloadRef.current(pl.data, typeof pl.wsUrl === "string" ? pl.wsUrl : null);
      },
    ).then((fn) => {
      unlisten = fn;
    });
    return () => {
      mounted = false;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    let mounted = true;
    let unlisten: (() => void) | undefined;
    void listen<PqProfitOverlayVpRelayPayload>(
      PQ_PROFIT_OVERLAY_VP_RELAY_EVENT,
      (ev) => {
        if (!mounted) return;
        const pl = ev.payload;
        if (!pl || typeof pl.data !== "string") return;
        try {
          if (pl.kind === "vp_overlay") {
            ingestVpOverlayMessage(JSON.parse(pl.data) as VpOverlayMessage);
          } else if (pl.kind === "volume_profile") {
            scheduleVolumeProfileCommit(JSON.parse(pl.data) as VolumeProfileMessage);
          }
        } catch {
          // ignore parse errors
        }
      },
    ).then((fn) => {
      unlisten = fn;
    });
    return () => {
      mounted = false;
      unlisten?.();
    };
  }, [ingestVpOverlayMessage, scheduleVolumeProfileCommit]);

  useEffect(() => {
    if (!isTauri()) return;
    const push = () => {
      void invoke("push_profit_overlay_rect_to_ocr").catch(() => {});
    };
    push();
    let deb: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (deb) clearTimeout(deb);
      deb = setTimeout(push, 120);
    };
    window.addEventListener("resize", schedule);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null;
    ro?.observe(document.documentElement);
    return () => {
      if (deb) clearTimeout(deb);
      window.removeEventListener("resize", schedule);
      ro?.disconnect();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const connectVpWs = () => {
      if (cancelled) return;
      if (
        vpWsRef.current?.readyState === WebSocket.OPEN ||
        vpWsRef.current?.readyState === WebSocket.CONNECTING
      ) {
        return;
      }
      const ws = new WebSocket(marketWsUrl("/ws/volume-profile"));
      vpWsRef.current = ws;

      ws.onopen = () => {
        vpWsBackoffRef.current = VP_WS_INITIAL_BACKOFF_MS;
      };
      ws.onmessage = (ev) => {
        try {
          if (vpOverlayPrimaryRef.current) return;
          applyVpTapeWsData(
            ev.data,
            applyVolumeProfileMessage,
            applyTapeIntelligenceMessage,
          );
        } catch {
          // ignore parse errors
        }
      };
      ws.onclose = () => {
        if (vpWsRef.current === ws) vpWsRef.current = null;
        if (cancelled) return;
        const delay = Math.min(vpWsBackoffRef.current, VP_WS_MAX_BACKOFF_MS);
        vpWsBackoffRef.current = Math.min(
          vpWsBackoffRef.current * 2,
          VP_WS_MAX_BACKOFF_MS,
        );
        clearTimeout(vpRetryTimer.current);
        vpRetryTimer.current = setTimeout(connectVpWs, delay);
      };
      ws.onerror = () => ws.close();
    };

    connectVpWs();
    return () => {
      cancelled = true;
      clearTimeout(vpRetryTimer.current);
      vpWsRef.current?.close();
      vpWsRef.current = null;
    };
  }, [applyTapeIntelligenceMessage, applyVolumeProfileMessage]);

  useEffect(() => {
    let cancelled = false;
    const connectVpOvWs = () => {
      if (cancelled) return;
      if (
        vpOvWsRef.current?.readyState === WebSocket.OPEN ||
        vpOvWsRef.current?.readyState === WebSocket.CONNECTING
      ) {
        return;
      }
      const ws = new WebSocket(marketWsUrl("/ws/vp-overlay"));
      vpOvWsRef.current = ws;
      ws.onopen = () => {
        vpOvBackoffRef.current = VP_WS_INITIAL_BACKOFF_MS;
      };
      ws.onmessage = (ev) => {
        try {
          const parsed = parseMarketWsPayload(ev.data);
          if (!parsed) return;
          if (parsed.topic === "ws_batch") {
            for (const item of (parsed as WsBatchMessage).items) {
              const t = (item as { type?: string }).type;
              if (item.topic === "market" && t === "vp_overlay") {
                ingestVpOverlayMessage(item as VpOverlayMessage);
              }
            }
            return;
          }
          const single = parsed as WsSingleMessage;
          if (single.topic === "market" && (single as { type?: string }).type === "vp_overlay") {
            ingestVpOverlayMessage(single as VpOverlayMessage);
          }
        } catch {
          // ignore parse errors
        }
      };
      ws.onclose = () => {
        if (vpOvWsRef.current === ws) vpOvWsRef.current = null;
        vpOverlayPrimaryRef.current = false;
        if (!cancelled) {
          setVpOverlayHealth(null);
          setVpOverlayRawTicker(null);
          setVpOverlayAgeMs(null);
        }
        if (cancelled) return;
        const delay = Math.min(vpOvBackoffRef.current, VP_WS_MAX_BACKOFF_MS);
        vpOvBackoffRef.current = Math.min(
          vpOvBackoffRef.current * 2,
          VP_WS_MAX_BACKOFF_MS,
        );
        clearTimeout(vpOvRetryTimer.current);
        vpOvRetryTimer.current = setTimeout(connectVpOvWs, delay);
      };
      ws.onerror = () => ws.close();
    };
    connectVpOvWs();
    return () => {
      cancelled = true;
      clearTimeout(vpOvRetryTimer.current);
      vpOvWsRef.current?.close();
      vpOvWsRef.current = null;
      vpOverlayPrimaryRef.current = false;
      setVpOverlayRawTicker(null);
      setVpOverlayAgeMs(null);
    };
  }, [ingestVpOverlayMessage]);

  useEffect(() => {
    const onResize = () => {
      setViewport({
        width: window.innerWidth,
        height: window.innerHeight,
        dpr: window.devicePixelRatio || 1,
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    const ignore = ocrHudCollapsed && !manualCalibrateMode;
    void invoke("set_profit_overlay_ignore_cursor_events", { ignore }).catch(() => {});
  }, [ocrHudCollapsed, manualCalibrateMode]);

  useEffect(() => {
    let mounted = true;
    const onExpand = (detail: unknown) => {
      if (!mounted) return;
      const p = detail as PqOverlayOcrDebugHudPayload | undefined;
      if (p && typeof p === "object" && p.expanded === true) setOcrHudCollapsed(false);
    };
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    if (isTauri()) {
      void (async () => {
        const fn = await listen(PQ_OVERLAY_OCR_DEBUG_HUD_EVENT, (ev) => {
          onExpand(ev.payload);
        });
        if (cancelled) {
          fn();
          return;
        }
        unlisten = fn;
      })();
    } else {
      const handler = (e: Event) => {
        const ce = e as CustomEvent<unknown>;
        onExpand(ce.detail);
      };
      window.addEventListener(PQ_OVERLAY_OCR_DEBUG_HUD_EVENT, handler as EventListener);
      unlisten = () =>
        window.removeEventListener(PQ_OVERLAY_OCR_DEBUG_HUD_EVENT, handler as EventListener);
    }
    return () => {
      mounted = false;
      cancelled = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      invoke<AppConfigRead>("read_config")
        .then((cfg) => {
          if (!mounted) return;
          applyOverlayConfigFromTauri(cfg);
        })
        .catch(() => {});
    };
    load();
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    if (isTauri()) {
      void (async () => {
        const fn = await listen(PQ_CONFIG_SAVED_EVENT, () => {
          if (mounted) load();
        });
        if (cancelled) {
          fn();
          return;
        }
        unlisten = fn;
      })();
    } else {
      const onConfigSaved = () => {
        if (mounted) load();
      };
      window.addEventListener(PQ_CONFIG_SAVED_EVENT, onConfigSaved);
      unlisten = () =>
        window.removeEventListener(PQ_CONFIG_SAVED_EVENT, onConfigSaved);
    }
    return () => {
      mounted = false;
      cancelled = true;
      unlisten?.();
    };
  }, [applyOverlayConfigFromTauri]);

  useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const root = document.getElementById("root");
    const prevHtml = html.style.background;
    const prevHtmlColor = html.style.backgroundColor;
    const prevHtmlImage = html.style.backgroundImage;
    const prevHtmlColorScheme = html.style.colorScheme;
    const prevBody = body.style.background;
    const prevBodyColor = body.style.backgroundColor;
    const prevBodyImage = body.style.backgroundImage;
    const prevBodyMargin = body.style.margin;
    const prevBodyOverflow = body.style.overflow;
    const prevRoot = root?.style.background ?? "";
    const prevRootColor = root?.style.backgroundColor ?? "";
    const prevRootImage = root?.style.backgroundImage ?? "";

    html.style.background = "transparent";
    html.style.backgroundColor = "transparent";
    html.style.backgroundImage = "none";
    html.style.colorScheme = "normal";
    body.style.background = "transparent";
    body.style.backgroundColor = "transparent";
    body.style.backgroundImage = "none";
    body.style.margin = "0";
    body.style.overflow = "hidden";
    if (root) {
      root.style.background = "transparent";
      root.style.backgroundColor = "transparent";
      root.style.backgroundImage = "none";
    }

    return () => {
      html.style.background = prevHtml;
      html.style.backgroundColor = prevHtmlColor;
      html.style.backgroundImage = prevHtmlImage;
      html.style.colorScheme = prevHtmlColorScheme;
      body.style.background = prevBody;
      body.style.backgroundColor = prevBodyColor;
      body.style.backgroundImage = prevBodyImage;
      body.style.margin = prevBodyMargin;
      body.style.overflow = prevBodyOverflow;
      if (root) {
        root.style.background = prevRoot;
        root.style.backgroundColor = prevRootColor;
        root.style.backgroundImage = prevRootImage;
      }
    };
  }, []);

  useEffect(() => {
    document.documentElement.classList.add("pq-overlay-profit");
    return () => document.documentElement.classList.remove("pq-overlay-profit");
  }, []);

  const renderScale = useMemo(() => {
    const dpr = viewport.dpr || 1;
    if (!Number.isFinite(dpr) || dpr <= 0) return 1;
    return 1 / dpr;
  }, [viewport.dpr]);

  const W = viewport.width;
  const H = viewport.height;
  const safeOverlayLines = useMemo(
    () => (Array.isArray(data.lines) ? data.lines : []),
    [data.lines],
  );
  const scaledLines = useMemo(
    () =>
      safeOverlayLines.map((line) => ({
        ...line,
        y_screen: line.y_screen * renderScale,
        chart_left: line.chart_left * renderScale,
        chart_right: line.chart_right * renderScale,
      })),
    [safeOverlayLines, renderScale],
  );
  const positionedLines = useMemo(() => layoutOverlayLines(scaledLines, H), [scaledLines, H]);
  const axisUsability = useMemo(() => isAxisUsableForOcr(data), [data]);
  const overlayPhase = useMemo<OverlayOcrPhase>(() => {
    if (startupEventState === "error") return "degraded";
    if (startupEventState === "starting") {
      const hasRecentOcrFeed =
        lastPayloadAtMs != null && Date.now() - lastPayloadAtMs < 15_000;
      if (!hasRecentOcrFeed) return "ocr_starting";
    }
    if (data.status === "ocr_connecting" || data.status === "connecting") return "ocr_connecting";
    if (
      data.status === "ocr_warming" ||
      data.status === "warming_up" ||
      data.status === "ocr_axis_warming"
    ) {
      return "ocr_warming";
    }
    const axPhase = normalizeAxisStatus(data.normalized_axis_status ?? data.axis_status ?? "");
    if (axPhase === "geometry_calibrating") return "geometry_calibrating";
    if (!axisUsability.usable) {
      const labelsOk = Number(data.parsed_labels_count ?? 0) >= 3;
      const fitReady = overlayAxisFitReady(data);
      if (data.axis_error_code && !(labelsOk && fitReady)) return "degraded";
      return "axis_waiting";
    }
    if (data.axis_error_code && axPhase === "suspect") return "axis_stable";
    return "axis_stable";
  }, [
    axisUsability.usable,
    data.axis_error_code,
    data.axis_status,
    data.normalized_axis_status,
    data.status,
    startupEventState,
    lastPayloadAtMs,
  ]);
  const scaledChartRect = useMemo(
    () => (axisUsability.usable ? scaleChartRect(data.chart_rect, renderScale) : null),
    [axisUsability.usable, data.chart_rect, renderScale],
  );
  const debugVisual = useMemo(
    () => normalizeDebugVisual(data.debug_visual, renderScale),
    [data.debug_visual, renderScale],
  );
  const fallbackVpChartRect = useMemo(
    () => (volumeProfile ? fallbackChartRectForVp(W, H) : null),
    [H, W, volumeProfile],
  );
  const liveEffectiveChartRect = scaledChartRect ?? fallbackVpChartRect;
  const effectiveFallbackReason = useMemo(() => {
    if (scaledChartRect) return "";
    return axisUsability.reason || "axis_unavailable";
  }, [axisUsability.reason, scaledChartRect]);
  const effectiveLastPayloadAgeMs = useMemo(() => {
    if (!Number.isFinite(lastPayloadAtMs) || lastPayloadAtMs == null) return null;
    return Math.max(0, Date.now() - lastPayloadAtMs);
  }, [lastPayloadAtMs, data.payload_seq]);
  const vpRange = useMemo(() => volumeProfilePriceRange(volumeProfile), [volumeProfile]);

  useEffect(() => {
    const t = volumeProfile?.ticker;
    if (t !== lastVpTickerRef.current) {
      lastVpTickerRef.current = t;
      setFallbackYLock(null);
      lastGoodSvgFrameRef.current = null;
      displayedSvgFrameRef.current = null;
    }
  }, [volumeProfile?.ticker]);

  useEffect(() => {
    if (scaledChartRect != null) {
      setFallbackYLock(null);
      return;
    }
    const mode = (vpFallbackMode || "auto").trim().toLowerCase();
    if (mode === "manual") return;
    if (vpRange == null) return;
    setFallbackYLock((prev) => prev ?? { min: vpRange.min, max: vpRange.max });
  }, [scaledChartRect, vpRange, vpFallbackMode]);

  const manualTop = vpFallbackPriceTop;
  const manualBot = vpFallbackPriceBot;
  const manualCalibrationOk =
    (vpFallbackMode || "auto").trim().toLowerCase() === "manual" &&
    typeof manualTop === "number" &&
    typeof manualBot === "number" &&
    Number.isFinite(manualTop) &&
    Number.isFinite(manualBot) &&
    manualTop !== manualBot;

  const effectiveYMin = scaledChartRect
    ? data.y_min
    : manualCalibrationOk
      ? Math.min(manualTop, manualBot)
      : fallbackYLock
        ? fallbackYLock.min
        : (vpRange?.min ?? null);
  const effectiveYMax = scaledChartRect
    ? data.y_max
    : manualCalibrationOk
      ? Math.max(manualTop, manualBot)
      : fallbackYLock
        ? fallbackYLock.max
        : (vpRange?.max ?? null);

  const overlaySnap = useMemo<OverlayLayoutSnapshot>(
    () => ({
      viewportWidth: W,
      viewportHeight: H,
      devicePixelRatio: viewport.dpr || 1,
      overlayRightMarginPx,
      showVolumeProfileOverlay,
      showTapeIntelligenceOverlay,
      vpFallbackMode,
      fallbackYLock,
      manualTop,
      manualBot,
      data: {
        lines: safeOverlayLines,
        status: data.status,
        y_min: data.y_min,
        y_max: data.y_max,
        chart_rect: data.chart_rect ?? null,
        geometry: data.geometry ?? null,
        axis_fit: data.axis_fit ?? null,
        axis_id: data.axis_id ?? null,
        axis_samples: data.axis_samples ?? null,
        axis_status: data.axis_status ?? null,
        normalized_axis_status:
          data.normalized_axis_status ?? normalizeAxisStatus(data.axis_status ?? ""),
        last_good_axis_age_ms: data.last_good_axis_age_ms ?? null,
        parsed_labels_count: data.parsed_labels_count ?? null,
      },
      volumeProfile,
      tapeIntelligence,
      effectiveVpDisplay,
      axisUsableForOcr: axisUsability.usable,
      axisUnusableReason: axisUsability.reason,
    }),
    [
      W,
      H,
      viewport.dpr,
      overlayRightMarginPx,
      showVolumeProfileOverlay,
      showTapeIntelligenceOverlay,
      vpFallbackMode,
      fallbackYLock,
      manualTop,
      manualBot,
      safeOverlayLines,
      data.status,
      data.y_min,
      data.y_max,
      data.chart_rect,
      data.geometry,
      data.axis_fit,
      data.axis_id,
      data.axis_samples,
      data.axis_status,
      data.normalized_axis_status,
      data.last_good_axis_age_ms,
      data.parsed_labels_count,
      volumeProfile,
      tapeIntelligence,
      effectiveVpDisplay,
      axisUsability.usable,
      axisUsability.reason,
    ],
  );

  useEffect(() => {
    const hasUsableAxis = axisUsability.usable;
    const hasLastFrame = lastGoodSvgFrameRef.current != null;
    if (!hasUsableAxis && hasLastFrame) {
      if (frozenByNoAxisRef.current) return;
      frozenByNoAxisRef.current = true;
      setSvgRafNonce((n) => n + 1);
      return;
    }
    if (hasUsableAxis) {
      frozenByNoAxisRef.current = false;
    }
  }, [axisUsability.usable]);

  useLayoutEffect(() => {
    snapshotDraftRef.current = overlaySnap;
  }, [overlaySnap]);

  useEffect(() => {
    let rafId = 0;
    let lastTs = 0;
    const loop = (now: number) => {
      rafId = requestAnimationFrame(loop);
      if (now - lastTs < 1000 / OVERLAY_VISUAL_FPS) return;
      lastTs = now;
      const snap = snapshotDraftRef.current;
      if (!snap) return;
      const r = safeBuildOverlayFrame(snap);
      if (r.error) {
        lastRenderErrRef.current = r.error.message ?? String(r.error);
      } else {
        lastRenderErrRef.current = null;
      }
      if (!r.viewportInvalid && r.frame && !r.error) {
        lastGoodSvgFrameRef.current = r.frame;
      }
      const nextFrame = !r.viewportInvalid && r.frame ? r.frame : lastGoodSvgFrameRef.current;
      displayedSvgFrameRef.current = nextFrame;

      const ws = wsRef.current;
      const vpOv = vpOvWsRef.current;
      const diag = readOverlayDiagEnv();
      const gf = displayedSvgFrameRef.current;
      const gl = snap.data.last_good_axis_age_ms;
      const vpSnap = snap.volumeProfile;
      const vpSnapLevels = vpSnap?.levels;
      const ocrFeedUp =
        (isTauri() && ocrRelayConnectedRef.current) ||
        (ws != null && ws.readyState === WebSocket.OPEN);
      const wsConnectedDiag =
        ocrFeedUp &&
        vpOv != null &&
        vpOv.readyState === WebSocket.OPEN;
      const positionedN = gf && Array.isArray(gf.positionedLines) ? gf.positionedLines.length : 0;
      const tapeN = gf && Array.isArray(gf.tapeBadges) ? gf.tapeBadges.length : 0;
      const vpLevelsN =
        gf?.volumeProfileOverlay?.levels != null && Array.isArray(gf.volumeProfileOverlay.levels)
          ? gf.volumeProfileOverlay.levels.length
          : 0;
      overlayHeartbeatRef.current = {
        overlay_mounted: true,
        window_width: snap.viewportWidth,
        window_height: snap.viewportHeight,
        device_pixel_ratio: snap.devicePixelRatio,
        axis_status: snap.data.axis_status ?? null,
        last_good_axis_exists:
          typeof gl === "number" && Number.isFinite(gl) && gl >= 0 && gl < 86400000,
        last_valid_vp_exists: Array.isArray(vpSnapLevels) && vpSnapLevels.length > 0,
        last_render_frame_exists: lastGoodSvgFrameRef.current != null,
        render_items_count: gf ? positionedN + tapeN + vpLevelsN : 0,
        last_render_error: lastRenderErrRef.current,
        ws_connected: wsConnectedDiag,
        black_screen_guard_active: !!(gf != null && gf.guardStatus !== "OK"),
        pq_diag_static_badge: diag.diagStaticBadge,
      };
      window.__PQ_OVERLAY_CONTEXT__ = {
        axis_status: snap.data.axis_status ?? null,
        last_good_axis: snap.data.last_good_axis_age_ms ?? null,
        last_valid_vp: {
          exists: Array.isArray(vpSnapLevels) && vpSnapLevels.length > 0,
          ticker: typeof vpSnap?.ticker === "string" ? vpSnap.ticker : undefined,
          levels: Array.isArray(vpSnapLevels) ? vpSnapLevels.length : 0,
        },
        last_render_frame: {
          exists: lastGoodSvgFrameRef.current != null,
          guardStatus: gf?.guardStatus,
        },
        render_items_count: gf ? positionedN + tapeN + vpLevelsN : 0,
        ws_connected: wsConnectedDiag,
        overlay_status: snap.data.status,
      };
      const nextCommitted = displayedSvgFrameRef.current;
      const nextDigest = overlayVisualCommitDigest(nextCommitted, snap);
      if (
        sameFrame(rafLastPushedFrameRef.current, nextCommitted) &&
        nextDigest === lastSvgVisualDigestRef.current
      ) {
        return;
      }
      rafLastPushedFrameRef.current = nextCommitted;
      lastSvgVisualDigestRef.current = nextDigest;
      setSvgRafNonce((n) => n + 1);
    };
    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      console.debug("[overlay-heartbeat]", { ...overlayHeartbeatRef.current });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onWindowError = (ev: ErrorEvent) => {
      const payload: Record<string, unknown> = {
        ts: Date.now(),
        message: ev.message ?? "",
        filename: ev.filename ?? "",
        lineno: ev.lineno,
        colno: ev.colno,
      };
      if (ev.error instanceof Error && typeof ev.error.stack === "string") {
        payload.stack = ev.error.stack;
      }
      try {
        localStorage.setItem(PQ_LAST_OVERLAY_WINDOW_ERROR_KEY, JSON.stringify(payload));
      } catch {
        // ignore
      }
      window.__PQ_LAST_OVERLAY_WINDOW_ERROR__ = payload;
    };
    const onUnhandledRejection = (ev: PromiseRejectionEvent) => {
      const reason = ev.reason;
      const message = reason instanceof Error ? reason.message : String(reason ?? "unknown");
      const payload: Record<string, unknown> = { ts: Date.now(), message };
      if (reason instanceof Error && typeof reason.stack === "string") {
        payload.stack = reason.stack;
      }
      try {
        localStorage.setItem(PQ_LAST_OVERLAY_PROMISE_ERROR_KEY, JSON.stringify(payload));
      } catch {
        // ignore
      }
      window.__PQ_LAST_OVERLAY_PROMISE_ERROR__ = payload;
    };
    window.addEventListener("error", onWindowError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => {
      window.removeEventListener("error", onWindowError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  void svgRafNonce;

  const gf = displayedSvgFrameRef.current;
  const effectiveVolumeProfileOverlay = gf?.volumeProfileOverlay ?? null;
  const histogramVisible =
    gf?.histogramVisible ??
    (effectiveVpDisplay?.histogram_visible !== false && showVolumeProfileOverlay);
  const positionedLinesCommitted = gf?.positionedLines ?? [];
  const overlayLinesDrawBase = gf != null ? positionedLinesCommitted : positionedLines;
  const overlayLinesDraw = axisUsability.usable ? overlayLinesDrawBase : [];
  const showLegacyOverlayIndicators =
    gf?.showLegacyOverlayIndicators ?? !effectiveVolumeProfileOverlay;
  const showMetricOverlayLines = gf?.showMetricOverlayLines ?? false;
  const showOcrOverlayLines = showLegacyOverlayIndicators || showMetricOverlayLines;
  const metricLineCandidates = effectiveVolumeProfileOverlay
    ? safeOverlayLines.filter((ln) => isMetricOcrOverlayLine(ln.label)).length
    : overlayLinesDraw.length;
  const metricLineVisibleCount = showOcrOverlayLines ? overlayLinesDraw.length : 0;
  const legacyLabelCollisionsCount = showOcrOverlayLines
    ? countDenseLabelCollisions(safeOverlayLines)
    : 0;
  const tapeBadgesCommitted = gf?.tapeBadges ?? [];
  const tapeOverlayDraw = gf != null ? tapeBadgesCommitted : [];
  /** Prefer last committed SVG frame geometry; fallback to live for debug / bootstrap. */
  const effectiveChartRect = gf?.effectiveChartRect ?? liveEffectiveChartRect;
  const overlayAlignmentMaxDeltaPx = useMemo(() => {
    void svgRafNonce;
    const chart = displayedSvgFrameRef.current?.effectiveChartRect;
    const vpo = displayedSvgFrameRef.current?.volumeProfileOverlay;
    if (!vpo || !chart) return null;
    const yMinSvg = displayedSvgFrameRef.current?.effectiveYMin ?? effectiveYMin;
    const yMaxSvg = displayedSvgFrameRef.current?.effectiveYMax ?? effectiveYMax;
    const deltas = [
      alignmentDeltaPx(vpo.pocY ?? undefined, vpo.poc, chart, renderScale, yMinSvg, yMaxSvg),
      alignmentDeltaPx(vpo.valY ?? undefined, vpo.val, chart, renderScale, yMinSvg, yMaxSvg),
      alignmentDeltaPx(vpo.vahY ?? undefined, vpo.vah, chart, renderScale, yMinSvg, yMaxSvg),
    ].filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    if (deltas.length === 0) return null;
    return Math.max(...deltas);
  }, [svgRafNonce, effectiveYMax, effectiveYMin, renderScale]);

  useEffect(() => {
    if (firstAxisStableLoggedRef.current) return;
    if (!axisUsability.usable) return;
    if (wsStartRef.current == null) return;
    const ms = Math.round(performance.now() - wsStartRef.current);
    console.info(`[overlay-metric] first_axis_stable_ms=${ms}`);
    firstAxisStableLoggedRef.current = true;
  }, [axisUsability.usable]);

  useEffect(() => {
    if (firstLinesRenderedLoggedRef.current) return;
    if (!axisUsability.usable || overlayLinesDraw.length === 0) return;
    if (wsStartRef.current == null) return;
    const ms = Math.round(performance.now() - wsStartRef.current);
    console.info(`[overlay-metric] first_lines_rendered_ms=${ms}`);
    firstLinesRenderedLoggedRef.current = true;
  }, [axisUsability.usable, overlayLinesDraw.length]);

  useEffect(() => {
    const t = performance.now();
    if (overlayPerfBootRef.current) {
      overlayPerfBootRef.current = false;
      overlayPerfLastRef.current = t;
      return;
    }
    const dt = t - overlayPerfLastRef.current;
    overlayPerfLastRef.current = t;
    if (dt > 0.2 && dt < 8000) {
      const ms = Math.round(dt * 10) / 10;
      const hz = Math.min(144, Math.round(1000 / dt));
      setOverlayCommitMs((prev) => (Object.is(prev, ms) ? prev : ms));
      setOverlayCommitHz((prev) => (Object.is(prev, hz) ? prev : hz));
    }
  }, [svgRafNonce]);

  const captureManualPoint = useCallback(
    (y: number) => {
      if (!manualCalibrateMode) return;
      const p = { y, value: "" };
      if (!manualPointA) {
        setManualPointA(p);
        return;
      }
      if (!manualPointB) {
        setManualPointB(p);
        return;
      }
      setManualPointA(manualPointB);
      setManualPointB(p);
    },
    [manualCalibrateMode, manualPointA, manualPointB],
  );

  const submitManualCalibration = useCallback(() => {
    if (!isTauri()) return;
    if (!manualPointA || !manualPointB) {
      setManualCalibrateHint("Selecione 2 pontos no overlay");
      window.setTimeout(() => setManualCalibrateHint(null), 3500);
      return;
    }
    const aValue = Number(manualPointA.value.replace(",", "."));
    const bValue = Number(manualPointB.value.replace(",", "."));
    if (!Number.isFinite(aValue) || !Number.isFinite(bValue) || aValue === bValue) {
      setManualCalibrateHint("Preços inválidos (A/B)");
      window.setTimeout(() => setManualCalibrateHint(null), 3500);
      return;
    }
    void invoke<{ ok?: boolean; message?: string }>("manual_calibrate_profit_ocr", {
      body: {
        points: [
          { value: aValue, y_screen: manualPointA.y / renderScale },
          { value: bValue, y_screen: manualPointB.y / renderScale },
        ],
      },
    })
      .then((r) => {
        setManualCalibrateHint(r?.message ?? "manual_axis_applied");
        setManualCalibrateMode(false);
      })
      .catch((e) =>
        setManualCalibrateHint(e instanceof Error ? e.message : String(e ?? "erro")),
      );
    window.setTimeout(() => setManualCalibrateHint(null), 5000);
  }, [manualPointA, manualPointB, renderScale]);

  const returnToAutoAxis = useCallback(() => {
    if (!isTauri()) return;
    void invoke<{ ok?: boolean; message?: string }>("unfreeze_profit_ocr")
      .then(() => invoke<{ ok?: boolean; message?: string }>("recalibrate_profit_ocr"))
      .then((r) => setManualCalibrateHint(r?.message ?? "recalibrating"))
      .catch((e) =>
        setManualCalibrateHint(e instanceof Error ? e.message : String(e ?? "erro")),
      );
    window.setTimeout(() => setManualCalibrateHint(null), 5000);
  }, []);
  const closeOverlayFromHud = useCallback(() => {
    if (!isTauri()) return;
    void invoke("close_profit_overlay", { reason: "overlay_hud_close_button" }).catch(() => {});
  }, []);

  const lineStatusSummary = useMemo(() => {
    const counters: Record<string, number> = {};
    for (const line of safeOverlayLines) {
      const key = canonicalizeLineStatus(line.status, line.out_of_bounds);
      counters[key] = (counters[key] ?? 0) + 1;
    }
    const preferredOrder = ["stable", "frozen", "out_of_bounds", "hidden", "unknown"];
    const parts: string[] = [];
    for (const key of preferredOrder) {
      if ((counters[key] ?? 0) > 0) parts.push(`${key}:${counters[key]}`);
      delete counters[key];
    }
    for (const [k, v] of Object.entries(counters)) {
      parts.push(`${k}:${v}`);
    }
    return parts.join(" · ");
  }, [safeOverlayLines]);
  const pqDiag = readOverlayDiagEnv();
  const axisDebugLayout = useMemo(() => {
    if (!pqDiag.debugAxisLabels) return null;
    const samples = data.axis_samples;
    const geom = data.geometry;
    if (!samples?.length || !geom?.overlay_rect_screen || !geom.chart_rect_screen) return null;
    const sf = geom.scale_factor > 0 && Number.isFinite(geom.scale_factor) ? geom.scale_factor : 1;
    const labelX = (geom.chart_rect_screen.left - geom.overlay_rect_screen.x) / sf + 4;
    const toY = (y_chart: number | null | undefined) => {
      if (y_chart == null || !Number.isFinite(y_chart)) return null;
      return overlayLineYCss(
        {
          value: 0,
          y_screen: 0,
          y_chart,
          color: "#000",
          chart_left: 0,
          chart_right: 0,
        },
        geom,
        renderScale,
        true,
      );
    };
    return { samples, labelX, toY };
  }, [pqDiag.debugAxisLabels, data.axis_samples, data.geometry, renderScale]);

  return (
    <div
      className="overlay-root overlay-window"
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        background: "transparent",
        backgroundColor: "transparent",
        backgroundImage: "none",
        overflow: "hidden",
        userSelect: "none",
        WebkitUserSelect: "none",
        colorScheme: "normal",
        forcedColorAdjust: "none",
      }}
    >
      {pqDiag.diagStaticBadge ? (
        <div
          style={{
            position: "absolute",
            top: 6,
            left: 8,
            padding: "3px 8px",
            borderRadius: 4,
            fontSize: 10,
            fontFamily: FONT,
            fontWeight: 700,
            background: "rgba(14,116,144,0.45)",
            color: "rgba(224,242,254,0.96)",
            border: "1px solid rgba(103,232,249,0.45)",
            pointerEvents: "none",
            zIndex: 2,
          }}
        >
          PQ_OVERLAY_DIAG_STATIC
        </div>
      ) : null}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="overlay-canvas overlay-window"
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        style={{ position: "absolute", inset: 0, display: "block", pointerEvents: manualCalibrateMode ? "auto" : "none" }}
        onClick={(ev) => {
          if (!manualCalibrateMode) return;
          const bounds = (ev.currentTarget as SVGElement).getBoundingClientRect();
          const y = clamp(ev.clientY - bounds.top, 0, H);
          captureManualPoint(y);
        }}
      >
        {showVisualDebug && debugLayerVisibility.bounds && (debugVisual?.bounds ?? scaledChartRect) ? (
          <g>
            <rect
              x={(debugVisual?.bounds ?? scaledChartRect)!.left}
              y={(debugVisual?.bounds ?? scaledChartRect)!.top}
              width={(debugVisual?.bounds ?? scaledChartRect)!.width}
              height={(debugVisual?.bounds ?? scaledChartRect)!.height}
              fill="none"
              stroke="rgba(56,189,248,0.88)"
              strokeWidth={1.2}
              strokeDasharray="6 4"
            />
            <text
              x={(debugVisual?.bounds ?? scaledChartRect)!.left + 6}
              y={(debugVisual?.bounds ?? scaledChartRect)!.top - 6}
              fill="rgba(125,211,252,0.96)"
              fontSize={10}
              fontFamily={FONT}
              fontWeight={700}
            >
              BOUNDS OCR
            </text>
          </g>
        ) : null}
        {showVisualDebug && debugLayerVisibility.roi && debugVisual?.roi ? (
          <g>
            <rect
              x={debugVisual.roi.left}
              y={debugVisual.roi.top}
              width={debugVisual.roi.width}
              height={debugVisual.roi.height}
              fill="rgba(244,114,182,0.05)"
              stroke="rgba(244,114,182,0.86)"
              strokeWidth={1.1}
              strokeDasharray="5 5"
            />
            <text
              x={debugVisual.roi.left + 6}
              y={debugVisual.roi.top - 6}
              fill="rgba(249,168,212,0.95)"
              fontSize={10}
              fontFamily={FONT}
              fontWeight={700}
            >
              ANALYSIS ROI
            </text>
          </g>
        ) : null}
        {showVisualDebug && debugLayerVisibility.regression && debugVisual?.regression && (debugVisual.bounds ?? scaledChartRect) ? (
          <g>
            <line
              x1={(debugVisual.bounds ?? scaledChartRect)!.right - 2}
              y1={(debugVisual.bounds ?? scaledChartRect)!.top}
              x2={(debugVisual.bounds ?? scaledChartRect)!.right - 2}
              y2={(debugVisual.bounds ?? scaledChartRect)!.bottom}
              stroke="rgba(250,204,21,0.90)"
              strokeWidth={1.4}
              strokeDasharray="4 3"
            />
            <text
              x={(debugVisual.bounds ?? scaledChartRect)!.left + 6}
              y={(debugVisual.bounds ?? scaledChartRect)!.bottom + 14}
              fill="rgba(253,224,71,0.96)"
              fontSize={9}
              fontFamily={FONT}
              fontWeight={700}
            >
              {`REG slope:${debugVisual.regression.slope.toFixed(4)} v/px:${debugVisual.regression.valuePerPx.toFixed(4)}`}
            </text>
          </g>
        ) : null}
        {showVisualDebug &&
        debugLayerVisibility.ocrLabels &&
        debugVisual?.labels &&
        Array.isArray(debugVisual.labels) &&
        debugVisual.labels.length ? (
          <g>
            {debugVisual.labels.map((label, idx) => (
              <g key={`dbg-ocr-label-${idx}`}>
                <line
                  x1={Math.max(0, W - 180)}
                  y1={label.y_screen}
                  x2={Math.max(0, W - 16)}
                  y2={label.y_screen}
                  stroke="rgba(110,231,183,0.55)"
                  strokeWidth={1}
                  strokeDasharray="3 3"
                />
                <circle
                  cx={Math.max(0, W - 170)}
                  cy={label.y_screen}
                  r={2.5}
                  fill="rgba(16,185,129,0.95)"
                />
                <text
                  x={Math.max(0, W - 164)}
                  y={label.y_screen - 4}
                  fill="rgba(167,243,208,0.95)"
                  fontSize={9}
                  fontFamily={FONT}
                  fontWeight={700}
                >
                  {label.value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}
                </text>
              </g>
            ))}
          </g>
        ) : null}
        {axisDebugLayout
          ? axisDebugLayout.samples.map((s, i) => {
              const chartTop = data.geometry?.chart_rect_screen?.top;
              const chartY =
                s.y_chart != null && Number.isFinite(s.y_chart)
                  ? s.y_chart
                  : Number.isFinite(s.y_screen) && typeof chartTop === "number" && Number.isFinite(chartTop)
                    ? s.y_screen - chartTop
                    : null;
              const yReal = chartY != null ? axisDebugLayout.toY(chartY) : null;
              const yPred =
                s.y_predicted != null && Number.isFinite(s.y_predicted)
                  ? axisDebugLayout.toY(s.y_predicted)
                  : null;
              if (yReal == null || yPred == null) return null;
              const errRaw =
                s.error_px != null && Number.isFinite(s.error_px)
                  ? s.error_px
                  : Math.abs(yReal - yPred);
              const lx = axisDebugLayout.labelX;
              return (
                <g key={`axis-canonical-dbg-${i}`}>
                  <circle cx={lx} cy={yReal} r={3} fill="#22d3ee" opacity={0.92} />
                  <circle cx={lx} cy={yPred} r={3} fill="#e879f9" opacity={0.92} />
                  <line x1={lx} y1={yReal} x2={lx} y2={yPred} stroke="#ef4444" strokeWidth={1.2} />
                  <text
                    x={lx + 8}
                    y={(yReal + yPred) / 2}
                    fill="rgba(255,255,255,0.92)"
                    fontSize={9}
                    fontFamily={FONT}
                    fontWeight={700}
                  >
                    {`${s.value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} · ±${errRaw.toFixed(1)}px`}
                  </text>
                </g>
              );
            })
          : null}
        {effectiveVolumeProfileOverlay?.ySource === "fallback" ? (
          <g>
            <rect
              x={10}
              y={10}
              width={W - 20}
              height={34}
              rx={4}
              fill="rgba(185,28,28,0.94)"
              stroke="rgba(254,202,202,0.95)"
              strokeWidth={1}
            />
            <text
              x={18}
              y={33}
              fill="rgba(255,255,255,0.98)"
              fontSize={12}
              fontFamily={FONT}
              fontWeight={800}
            >
              {`FALLBACK VP — eixo OCR indisponível ou incompleto · modo ${(vpFallbackMode || "auto").trim()}`}
              {effectiveFallbackReason ? ` · ${effectiveFallbackReason}` : ""}
            </text>
          </g>
        ) : null}
        {showOcrOverlayLines
          ? overlayLinesDraw.map((line, i) => (
              <OverlayLineEl
                key={i}
                line={line}
                rightMarginPx={overlayRightMarginPx}
                vpProfileLeft={effectiveVolumeProfileOverlay?.profileLeft ?? null}
              />
            ))
          : null}
        {effectiveVolumeProfileOverlay ? (
          <VolumeProfileLayer overlay={effectiveVolumeProfileOverlay} showHistogram={histogramVisible} />
        ) : (
          showVolumeProfileOverlay &&
          effectiveChartRect && (
            <VolumeProfileWaitingBadge chart={effectiveChartRect} volumeProfile={volumeProfile} />
          )
        )}
        {tapeOverlayDraw.map((badge) => (
          <TapeBadge key={badge.key} badge={badge} />
        ))}
        {showVisualDebug && showOcrOverlayLines
          ? overlayLinesDraw.map((line, i) => {
              const status = canonicalizeLineStatus(line.status, line.out_of_bounds);
              return (
                <text
                  key={`dbg-line-${i}`}
                  x={Math.max(4, line.chart_left + 8)}
                  y={line.y_screen - 6}
                  fill="rgba(203,213,225,0.95)"
                  fontSize={9}
                  fontFamily={FONT}
                  fontWeight={700}
                >
                  {`${line.label ?? `L${i + 1}`}: ${status}`}
                </text>
              );
            })
          : null}
        {manualPointA ? (
          <g>
            <line x1={0} y1={manualPointA.y} x2={W} y2={manualPointA.y} stroke="rgba(250,204,21,0.85)" strokeWidth={1.2} />
            <text x={14} y={manualPointA.y - 6} fill="rgba(250,204,21,0.95)" fontSize={10} fontFamily={FONT} fontWeight={800}>
              A
            </text>
          </g>
        ) : null}
        {manualPointB ? (
          <g>
            <line x1={0} y1={manualPointB.y} x2={W} y2={manualPointB.y} stroke="rgba(52,211,153,0.88)" strokeWidth={1.2} />
            <text x={14} y={manualPointB.y - 6} fill="rgba(52,211,153,0.96)" fontSize={10} fontFamily={FONT} fontWeight={800}>
              B
            </text>
          </g>
        ) : null}

        <StatusBadge
          status={overlayPhase}
          overlayGuard={
            gf?.guardStatus === "OK"
              ? null
              : `${gf?.guardStatus ?? "?"} · frame ${gf != null ? "on" : "off"} · err ${lastRenderErrRef.current ?? "—"}`
          }
          y_min={data.y_min}
          y_max={data.y_max}
          axis_deltas={data.axis_deltas}
          axis_diagnostics={data.axis_diagnostics}
          alignmentMaxDeltaPx={overlayAlignmentMaxDeltaPx}
          viewportHeight={H}
          visibleLineCount={metricLineVisibleCount}
          visibleHistogramLevels={
            effectiveVolumeProfileOverlay?.levels != null &&
            Array.isArray(effectiveVolumeProfileOverlay.levels)
              ? effectiveVolumeProfileOverlay.levels.length
              : 0
          }
          histogramCandidates={effectiveVolumeProfileOverlay?.histogramCandidates ?? 0}
          histogramRendered={effectiveVolumeProfileOverlay?.histogramRendered ?? 0}
          histogramCoalesced={effectiveVolumeProfileOverlay?.histogramCoalesced ?? 0}
          avgLineVisibleCount={metricLineVisibleCount}
          avgLineCandidates={metricLineCandidates}
          labelCollisionsCount={legacyLabelCollisionsCount}
          overlayCommitMs={overlayCommitMs}
          overlayCommitHz={overlayCommitHz}
          axisStatus={data.axis_status ?? null}
          axisSource={data.axis_source ?? null}
          badFrames={data.bad_frames ?? null}
          axisErrorCode={data.axis_error_code ?? null}
          axisErrorMessage={data.axis_error_message ?? null}
          lastGoodAxisAgeMs={data.last_good_axis_age_ms ?? null}
          overlayWindowAlive={data.overlay_window_alive ?? null}
          ocrServiceAlive={data.ocr_service_alive ?? null}
          ocrWsConnected={data.ocr_ws_connected ?? null}
          vpStatus={data.vp_status ?? null}
          lineStatusSummary={lineStatusSummary}
          rawAxisStatus={data.raw_axis_status ?? data.axis_status ?? null}
          normalizedAxisStatus={data.normalized_axis_status ?? normalizeAxisStatus(data.axis_status ?? "")}
          fallbackReason={effectiveFallbackReason || null}
          payloadSeq={data.payload_seq ?? null}
          wsUrl={data.ws_url ?? ocrWsUrl}
          ocrPid={data.ocr_pid ?? null}
          ocrPort={data.ocr_port ?? null}
          parsedLabelsCount={data.parsed_labels_count ?? null}
          ocrConfidence={data.ocr_confidence ?? null}
          lastPayloadAgeMs={effectiveLastPayloadAgeMs}
          axisCaptureInitial={formatAxisCaptureLine("ini", axisCaptureInitial)}
          axisCaptureCurrent={formatAxisCaptureLine("agora", axisCaptureCurrent)}
        />
      </svg>
      <VpOverlayHud
        effective={effectiveVpDisplay}
        showVp={showVolumeProfileOverlay}
        showTi={showTapeIntelligenceOverlay}
        onPatch={patchVpOverlayPref}
        onRecalibrate={recalibrateOcr}
        onFreeze={freezeOcrAxis}
        onUnfreeze={unfreezeOcrAxis}
        recalibrateHint={recalibrateHint}
        axisActionHint={axisActionHint}
        manualCalibrateHint={manualCalibrateHint}
        vpPeriod={vpPeriodCfg}
        onVpPeriod={setVpPeriod}
        streamVpPeriod={volumeProfile?.period ?? null}
        health={vpOverlayHealth}
        vpOverlayRawTicker={vpOverlayRawTicker}
        vpOverlayAgeMs={vpOverlayAgeMs}
        showVisualDebug={showVisualDebug}
        onToggleVisualDebug={setShowVisualDebug}
        debugLayerVisibility={debugLayerVisibility}
        onToggleDebugLayer={(layer, value) =>
          setDebugLayerVisibility((prev) => ({ ...prev, [layer]: value }))
        }
        manualCalibrateMode={manualCalibrateMode}
        onToggleManualCalibrateMode={setManualCalibrateMode}
        manualPointA={manualPointA}
        manualPointB={manualPointB}
        onSetManualPointAValue={(value) =>
          setManualPointA((prev) => (prev ? { ...prev, value } : prev))
        }
        onSetManualPointBValue={(value) =>
          setManualPointB((prev) => (prev ? { ...prev, value } : prev))
        }
        onSubmitManualCalibration={submitManualCalibration}
        onClearManualCalibration={() => {
          setManualPointA(null);
          setManualPointB(null);
        }}
        onReturnAutoAxis={returnToAutoAxis}
        onCloseOverlay={closeOverlayFromHud}
        ocrHudCollapsed={ocrHudCollapsed}
        onSetOcrHudCollapsed={setOcrHudCollapsed}
      />
    </div>
  );
}

export interface VpOverlayHudProps {
  effective: VpOverlayDisplay;
  showVp: boolean;
  showTi: boolean;
  onPatch: (patch: Partial<VpOverlayPrefsConfig>) => void;
  onRecalibrate: () => void;
  onFreeze: () => void;
  onUnfreeze: () => void;
  recalibrateHint: string | null;
  axisActionHint: string | null;
  manualCalibrateHint: string | null;
  vpPeriod: "day" | "week" | "manual";
  onVpPeriod: (p: "day" | "week" | "manual") => void;
  streamVpPeriod: "day" | "week" | "manual" | null;
  health: Record<string, unknown> | null;
  overlayDebug?: {
    axisStatus: string | null;
    axisSource: string | null;
    badFrames: number | null;
    pendingFrames: number | null;
    labelsCount: number | null;
    residualPx: number | null;
    maxErrorPx: number | null;
    slope: number | null;
    intercept: number | null;
    valuePerPx: number | null;
    lineStatusSummary: string;
  };
  vpOverlayRawTicker: string | null;
  vpOverlayAgeMs: number | null;
  showVisualDebug: boolean;
  onToggleVisualDebug: (v: boolean) => void;
  debugLayerVisibility: {
    ocrLabels: boolean;
    regression: boolean;
    roi: boolean;
    bounds: boolean;
  };
  onToggleDebugLayer: (
    layer: "ocrLabels" | "regression" | "roi" | "bounds",
    value: boolean,
  ) => void;
  manualCalibrateMode: boolean;
  onToggleManualCalibrateMode: (v: boolean) => void;
  manualPointA: { y: number; value: string } | null;
  manualPointB: { y: number; value: string } | null;
  onSetManualPointAValue: (value: string) => void;
  onSetManualPointBValue: (value: string) => void;
  onSubmitManualCalibration: () => void;
  onClearManualCalibration: () => void;
  onReturnAutoAxis: () => void;
  onCloseOverlay: () => void;
  ocrHudCollapsed: boolean;
  onSetOcrHudCollapsed: (collapsed: boolean) => void;
}

export function VpOverlayHud({
  effective,
  showVp,
  showTi,
  onPatch,
  onRecalibrate,
  onFreeze,
  onUnfreeze,
  recalibrateHint,
  axisActionHint,
  manualCalibrateHint,
  vpPeriod,
  onVpPeriod,
  streamVpPeriod,
  health,
  overlayDebug,
  vpOverlayRawTicker,
  vpOverlayAgeMs,
  showVisualDebug,
  onToggleVisualDebug,
  debugLayerVisibility,
  onToggleDebugLayer,
  manualCalibrateMode,
  onToggleManualCalibrateMode,
  manualPointA,
  manualPointB,
  onSetManualPointAValue,
  onSetManualPointBValue,
  onSubmitManualCalibration,
  onClearManualCalibration,
  onReturnAutoAxis,
  onCloseOverlay,
  ocrHudCollapsed,
  onSetOcrHudCollapsed,
}: VpOverlayHudProps) {
  const chk = (k: keyof VpOverlayPrefsConfig, def: boolean) => {
    const v =
      k === "enabled"
        ? effective.overlay_enabled
        : effective[k as keyof VpOverlayDisplay];
    if (typeof v === "boolean") return v;
    return def;
  };
  const ocrConf =
    typeof health?.ocr_confidence === "number" && Number.isFinite(health.ocr_confidence)
      ? Math.round(Number(health.ocr_confidence) * 1000) / 1000
      : null;
  const axisStale =
    typeof health?.axis_stale_ms === "number" && Number.isFinite(health.axis_stale_ms)
      ? Math.round(Number(health.axis_stale_ms))
      : null;
  const dataStatus = typeof health?.data_status === "string" ? health.data_status : null;
  const lastTradeAge =
    typeof health?.last_trade_age_ms === "number" && Number.isFinite(health.last_trade_age_ms)
      ? Math.round(Number(health.last_trade_age_ms))
      : null;
  const axisStatus =
    typeof health?.axis_status === "string"
      ? health.axis_status
      : overlayDebug?.axisStatus ?? null;
  const axisSource =
    typeof health?.axis_source === "string"
      ? health.axis_source
      : overlayDebug?.axisSource ?? null;
  const badFramesRaw =
    typeof health?.bad_frames === "number" && Number.isFinite(health.bad_frames)
      ? Math.round(Number(health.bad_frames))
      : overlayDebug?.badFrames ?? null;
  const badFrames = badFramesRaw == null ? null : Math.max(0, Math.round(badFramesRaw));
  const pendingFrames =
    overlayDebug?.pendingFrames == null || !Number.isFinite(overlayDebug.pendingFrames)
      ? null
      : Math.max(0, Math.round(overlayDebug.pendingFrames));
  const overlayPublishAge =
    typeof health?.last_overlay_publish_age_ms === "number" && Number.isFinite(health.last_overlay_publish_age_ms)
      ? Math.round(Number(health.last_overlay_publish_age_ms))
      : null;
  const overlayAgeState =
    typeof health?.overlay_age_state === "string"
      ? health.overlay_age_state
      : overlayPublishAge == null
        ? "missing"
        : overlayPublishAge > 3000
          ? "stale"
          : "fresh";
  const manualPointAValue = manualPointA?.value ?? "";
  const manualPointBValue = manualPointB?.value ?? "";
  const hasManualPointA = manualPointA != null;
  const hasManualPointB = manualPointB != null;
  const parsedManualA = Number(manualPointAValue.replace(",", "."));
  const parsedManualB = Number(manualPointBValue.replace(",", "."));
  const hasValidManualA = Number.isFinite(parsedManualA);
  const hasValidManualB = Number.isFinite(parsedManualB);
  const sameManualPrice = hasValidManualA && hasValidManualB && parsedManualA === parsedManualB;
  const sameManualY =
    hasManualPointA && hasManualPointB && Math.abs(manualPointA.y - manualPointB.y) < 1;
  const canSubmitManualCalibration =
    hasManualPointA &&
    hasManualPointB &&
    hasValidManualA &&
    hasValidManualB &&
    !sameManualPrice &&
    !sameManualY;
  const manualValidationMessage = !hasManualPointA
    ? "Selecione o ponto A no overlay."
    : !hasManualPointB
      ? "Selecione o ponto B no overlay."
      : !hasValidManualA || !hasValidManualB
        ? "Informe preços numéricos válidos para A e B."
        : sameManualPrice
          ? "A e B precisam ter preços diferentes."
          : sameManualY
            ? "A e B precisam estar em alturas diferentes no gráfico."
            : null;
  const overlayAgeStateLabel =
    overlayAgeState === "missing" || overlayAgeState === "stale" || overlayAgeState === "fresh"
      ? overlayAgeState
      : "missing";
  const axisStatusNormalized = (axisStatus ?? "").trim().toUpperCase();
  const dataStatusNormalized = (dataStatus ?? "").trim().toLowerCase();
  const hasRuntimeError =
    dataStatusNormalized.startsWith("error") || dataStatusNormalized.includes("timeout");
  const hasAxisError =
    axisStatusNormalized.includes("ERROR") ||
    axisStatusNormalized === "NO_AXIS" ||
    axisStatusNormalized === "AXIS_NOT_FOUND";
  const hasFramePressure = (badFrames ?? 0) >= 3 || (pendingFrames ?? 0) >= 5;
  const overlayStatePriority: "error" | "alert" | "info" = hasRuntimeError || hasAxisError
    ? "error"
    : overlayAgeStateLabel === "missing"
      ? "error"
      : overlayAgeStateLabel === "stale" || hasFramePressure
        ? "alert"
        : "info";
  const overlayStateBadgeText =
    overlayStatePriority === "error"
      ? "ERRO"
      : overlayStatePriority === "alert"
        ? "ALERTA"
        : "INFO";
  const overlayStateLabel =
    overlayStatePriority === "error"
      ? "degradado"
      : overlayStatePriority === "alert"
        ? "instável"
        : "atualizado";
  const overlayReason =
    hasRuntimeError
      ? "falha no runtime OCR"
      : hasAxisError
        ? "eixo OCR inconsistente"
        : hasFramePressure
          ? "fila/bad frames elevados"
          : overlayAgeStateLabel === "missing"
            ? "sem payload recente"
            : overlayAgeStateLabel === "stale"
              ? "payload desatualizado"
              : "operação normal";
  const overlayAction =
    hasRuntimeError
      ? "manter overlay aberto e revisar logs do runtime OCR"
      : hasAxisError
        ? "acionar recalibrar eixo e validar leitura no gráfico"
        : hasFramePressure
          ? "reduzir carga visual e monitorar normalização dos frames"
          : overlayAgeStateLabel === "missing"
            ? "aguardar próximo payload ou reabrir overlay"
            : overlayAgeStateLabel === "stale"
              ? "validar estabilidade do feed antes de operar"
              : "operação normal: seguir monitorando";
  const canReturnAutoAxis =
    axisStatusNormalized === "MANUAL_LOCKED" ||
    (axisSource ?? "").trim().toLowerCase() === "manual";
  const hudPlaceholder = (value: string | number | null | undefined, placeholder: string): string =>
    value == null || value === "" ? placeholder : String(value);
  return (
    <div
      role="region"
      aria-label="Painel de debug do overlay"
      style={{
        position: "fixed",
        top: 8,
        right: 8,
        pointerEvents: ocrHudCollapsed ? "none" : "auto",
        zIndex: 50,
        fontFamily: FONT,
        fontSize: 11,
        color: "rgba(235,240,248,0.95)",
        background: "rgba(12,14,18,0.88)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 6,
        padding: ocrHudCollapsed ? "6px 10px" : "8px 10px",
        minWidth: 200,
        maxWidth: 280,
        boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: ocrHudCollapsed ? 0 : 6,
        }}
      >
        <div style={{ fontWeight: 800, letterSpacing: "0.06em", fontSize: 10 }}>OCR OVERLAY DEBUG</div>
        {!ocrHudCollapsed ? (
          <button
            type="button"
            onClick={() => onSetOcrHudCollapsed(true)}
            aria-label="Colapsar painel OCR overlay debug"
            style={{
              border: "1px solid rgba(255,255,255,0.22)",
              background: "rgba(0,0,0,0.45)",
              color: "inherit",
              borderRadius: 4,
              fontSize: 10,
              padding: "2px 6px",
              cursor: "pointer",
            }}
          >
            Colapsar
          </button>
        ) : null}
      </div>
      {ocrHudCollapsed ? (
        <div style={{ fontSize: 9, opacity: 0.65, marginTop: 4, pointerEvents: "none" }}>
          Expanda na janela de controlo (EXPANDIR OCR DEBUG).
        </div>
      ) : null}
      {!ocrHudCollapsed ? (
        <>
      <label style={{ ...vpHudRowStyle, flexWrap: "wrap" }}>
        <span style={{ flex: "1 1 100%", marginBottom: 2, opacity: 0.78, fontSize: 10 }}>
          Período VP (engine)
        </span>
        <select
          aria-label="Selecionar período do volume profile"
          value={vpPeriod}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "day" || v === "week" || v === "manual") onVpPeriod(v);
          }}
          style={{
            width: "100%",
            marginTop: 2,
            padding: "4px 6px",
            fontSize: 11,
            borderRadius: 4,
            border: "1px solid rgba(255,255,255,0.2)",
            background: "rgba(0,0,0,0.45)",
            color: "inherit",
          }}
        >
          <option value="day">Dia atual</option>
          <option value="week">Semana</option>
          <option value="manual">Manual</option>
        </select>
      </label>
      {streamVpPeriod ? (
        <div style={{ fontSize: 10, opacity: 0.72, marginBottom: 6, marginTop: -2 }}>
          {`Stream: ${streamVpPeriod}`}
        </div>
      ) : null}
      {health ? (
        <div
          aria-live="polite"
          style={{
            fontSize: 10,
            lineHeight: 1.35,
            opacity: 0.88,
            marginBottom: 8,
            padding: "6px 8px",
            borderRadius: 4,
            background: "rgba(0,0,0,0.35)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 4, opacity: 0.9 }}>Saúde / OCR</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>{`overlay: ${overlayStateLabel}`}</span>
            <span style={vpHudPriorityBadgeStyle(overlayStatePriority)}>{overlayStateBadgeText}</span>
          </div>
          <div>{`motivo: ${overlayReason}`}</div>
          <div>{`ação: ${overlayAction}`}</div>
          <div>{`raw: ${hudPlaceholder(vpOverlayRawTicker, "— sem ticker")}`}</div>
          <div>{`payload age: ${vpOverlayAgeMs != null ? `${Math.round(vpOverlayAgeMs)} ms` : "— sem dado"}`}</div>
          <div>{`publish age: ${overlayPublishAge != null ? `${overlayPublishAge} ms` : "— sem dado"}`}</div>
          <div>{`data: ${hudPlaceholder(dataStatus, "— sem status")}`}</div>
          <div>
            {`axis: ${axisStatus ? `${axisStatus}${axisSource ? ` / ${axisSource}` : ""}` : "— sem eixo"}`}
          </div>
          <div>{`bad frames: ${badFrames != null ? String(badFrames) : "— sem dado"}`}</div>
          <div>{`pending: ${pendingFrames != null ? String(pendingFrames) : "— sem dado"}`}</div>
          <div>{`OCR conf: ${ocrConf != null ? String(ocrConf) : "— sem dado"}`}</div>
          <div>{`eixo stale: ${axisStale != null ? `${axisStale} ms` : "— sem dado"}`}</div>
          <div>{`último trade: ${lastTradeAge != null ? `${lastTradeAge} ms` : "— sem dado"}`}</div>
        </div>
      ) : null}
      <label style={vpHudRowStyle}>
        <input
          type="checkbox"
          checked={chk("enabled", true)}
          onChange={(e) => onPatch({ enabled: e.target.checked })}
          aria-label="Ativar overlay"
        />
        Overlay ligado
      </label>
      <label style={{ ...vpHudRowStyle, opacity: showVp ? 1 : 0.45 }}>
        <input
          type="checkbox"
          disabled={!showVp}
          checked={chk("histogram_visible", true)}
          onChange={(e) => onPatch({ histogram_visible: e.target.checked })}
          aria-label="Exibir histograma do volume profile"
        />
        Histograma VP
      </label>
      <label style={vpHudRowStyle}>
        <input
          type="checkbox"
          checked={chk("poc_visible", true)}
          onChange={(e) => onPatch({ poc_visible: e.target.checked })}
          aria-label="Exibir linha POC"
        />
        Linha POC
      </label>
      <label style={vpHudRowStyle}>
        <input
          type="checkbox"
          checked={chk("val_vah_visible", true)}
          onChange={(e) => onPatch({ val_vah_visible: e.target.checked })}
          aria-label="Exibir linhas VAL e VAH"
        />
        Linhas VAL/VAH
      </label>
      <label style={{ ...vpHudRowStyle, opacity: showTi ? 1 : 0.45 }}>
        <input
          type="checkbox"
          disabled={!showTi}
          checked={chk("labels_visible", true)}
          onChange={(e) => onPatch({ labels_visible: e.target.checked })}
          aria-label="Exibir etiquetas de times and trades"
        />
        Etiquetas T&T
      </label>
      <label style={{ ...vpHudRowStyle, opacity: showTi ? 1 : 0.45 }}>
        <input
          type="checkbox"
          disabled={!showTi}
          checked={chk("top_avg_visible", true)}
          onChange={(e) => onPatch({ top_avg_visible: e.target.checked })}
          aria-label="Exibir linhas monitoradas UBS e líderes"
        />
        Linhas monitoradas (UBS / líderes)
      </label>
      <label style={vpHudRowStyle}>
        <input
          type="checkbox"
          checked={chk("stretch_lines", false)}
          onChange={(e) => onPatch({ stretch_lines: e.target.checked })}
          aria-label="Esticar linhas no gráfico"
        />
        Esticar linhas
      </label>
      <label style={vpHudRowStyle}>
        <input
          type="checkbox"
          checked={showVisualDebug}
          onChange={(e) => onToggleVisualDebug(e.target.checked)}
          aria-label="Ativar camada de debug visual OCR"
        />
        Debug visual OCR (camadas)
      </label>
      {showVisualDebug ? (
        <div
          style={{
            marginBottom: 6,
            padding: "6px 8px",
            borderRadius: 4,
            border: "1px solid rgba(255,255,255,0.1)",
            background: "rgba(0,0,0,0.28)",
          }}
        >
          <label style={vpHudRowStyle}>
            <input
              type="checkbox"
              checked={debugLayerVisibility.ocrLabels}
              onChange={(e) => onToggleDebugLayer("ocrLabels", e.target.checked)}
              aria-label="Exibir labels OCR"
            />
            Labels OCR
          </label>
          <label style={vpHudRowStyle}>
            <input
              type="checkbox"
              checked={debugLayerVisibility.regression}
              onChange={(e) => onToggleDebugLayer("regression", e.target.checked)}
              aria-label="Exibir linha de regressão OCR"
            />
            Regressao
          </label>
          <label style={vpHudRowStyle}>
            <input
              type="checkbox"
              checked={debugLayerVisibility.roi}
              onChange={(e) => onToggleDebugLayer("roi", e.target.checked)}
              aria-label="Exibir região de interesse OCR"
            />
            ROI
          </label>
          <label style={{ ...vpHudRowStyle, marginBottom: 0 }}>
            <input
              type="checkbox"
              checked={debugLayerVisibility.bounds}
              onChange={(e) => onToggleDebugLayer("bounds", e.target.checked)}
              aria-label="Exibir bounds do gráfico OCR"
            />
            Bounds
          </label>
        </div>
      ) : null}
      <label style={vpHudRowStyle}>
        <input
          type="checkbox"
          checked={manualCalibrateMode}
          onChange={(e) => onToggleManualCalibrateMode(e.target.checked)}
          aria-label="Ativar calibração manual em dois pontos"
        />
        Calibração manual (2 pontos)
      </label>
      {manualCalibrateMode ? (
        <div
          style={{
            marginBottom: 8,
            padding: "6px 8px",
            borderRadius: 4,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(0,0,0,0.28)",
          }}
        >
          <div style={{ fontSize: 10, opacity: 0.82, marginBottom: 4 }}>
            Capture os pontos A/B no overlay e informe os preços para aplicar o eixo manual.
          </div>
          <div style={{ display: "flex", gap: 6, marginBottom: 4 }}>
            <input
              type="text"
              placeholder="Preço A"
              value={manualPointA?.value ?? ""}
              onChange={(e) => onSetManualPointAValue(e.target.value)}
              style={{ ...vpHudNumStyle, width: 88 }}
              aria-label="Preço do ponto A"
            />
            <input
              type="text"
              placeholder="Preço B"
              value={manualPointB?.value ?? ""}
              onChange={(e) => onSetManualPointBValue(e.target.value)}
              style={{ ...vpHudNumStyle, width: 88 }}
              aria-label="Preço do ponto B"
            />
          </div>
          <div style={{ fontSize: 10, opacity: 0.72, marginBottom: 6 }}>
            {`A y: ${manualPointA ? Math.round(manualPointA.y) : "—"} · B y: ${manualPointB ? Math.round(manualPointB.y) : "—"}`}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              disabled={!canSubmitManualCalibration}
              onClick={onSubmitManualCalibration}
              style={{
                ...vpHudActionBtn,
                opacity: canSubmitManualCalibration ? 1 : 0.5,
                cursor: canSubmitManualCalibration ? "pointer" : "not-allowed",
              }}
              title={manualValidationMessage ?? undefined}
              aria-label="Aplicar calibração manual"
            >
              Aplicar eixo manual
            </button>
            <button
              type="button"
              onClick={onClearManualCalibration}
              style={vpHudActionBtn}
              aria-label="Limpar pontos de calibração manual"
            >
              Limpar pontos
            </button>
          </div>
          {manualValidationMessage ? (
            <div
              style={{
                marginTop: 6,
                fontSize: 10,
                color: "rgba(253,230,138,0.95)",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span style={vpHudPriorityBadgeStyle("alert")}>ALERTA</span>
              {manualValidationMessage}
            </div>
          ) : null}
        </div>
      ) : null}
      <div style={{ ...vpHudRowStyle, alignItems: "center", gap: 8 }}>
        <span style={{ flex: "0 0 auto" }}>max níveis hist.</span>
        <input
          type="number"
          min={8}
          max={2000}
          style={vpHudNumStyle}
          aria-label="Quantidade máxima de níveis de histograma"
          value={
            typeof effective.max_visible_histogram_levels === "number" &&
            Number.isFinite(effective.max_visible_histogram_levels)
              ? Math.min(2000, Math.max(8, Number(effective.max_visible_histogram_levels)))
              : 400
          }
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (!Number.isFinite(n)) return;
            onPatch({
              max_visible_histogram_levels: Math.min(2000, Math.max(8, n)),
            });
          }}
        />
      </div>
      {isTauri() ? (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <button
            type="button"
            onClick={onRecalibrate}
            aria-label="Executar recalibração automática"
            style={{
              flex: 1,
              padding: "6px 8px",
              fontSize: 10,
              fontWeight: 700,
              cursor: "pointer",
              borderRadius: 4,
              border: "1px solid rgba(251,191,36,0.55)",
              background: "rgba(251,191,36,0.12)",
              color: "rgba(253,230,138,0.98)",
            }}
          >
            Recalibrar eixo
          </button>
          <button
            type="button"
            onClick={onFreeze}
            aria-label="Congelar eixo manualmente"
            style={{
              flex: 1,
              padding: "6px 8px",
              fontSize: 10,
              fontWeight: 700,
              cursor: "pointer",
              borderRadius: 4,
              border: "1px solid rgba(248,113,113,0.55)",
              background: "rgba(248,113,113,0.12)",
              color: "rgba(254,202,202,0.98)",
            }}
          >
            Freeze
          </button>
          <button
            type="button"
            onClick={onUnfreeze}
            aria-label="Descongelar eixo manualmente"
            style={{
              flex: 1,
              padding: "6px 8px",
              fontSize: 10,
              fontWeight: 700,
              cursor: "pointer",
              borderRadius: 4,
              border: "1px solid rgba(52,211,153,0.55)",
              background: "rgba(52,211,153,0.12)",
              color: "rgba(167,243,208,0.98)",
            }}
          >
            Retomar
          </button>
        </div>
      ) : null}
      {recalibrateHint ? (
        <div
          style={{ marginTop: 6, fontSize: 10, color: "rgba(180,220,255,0.92)" }}
          aria-live="polite"
        >
          <span style={{ ...vpHudPriorityBadgeStyle("info"), marginRight: 6 }}>INFO</span>
          {recalibrateHint}
        </div>
      ) : null}
      {axisActionHint ? (
        <div
          style={{ marginTop: 6, fontSize: 10, color: "rgba(180,220,255,0.92)" }}
          aria-live="polite"
        >
          <span style={{ ...vpHudPriorityBadgeStyle("info"), marginRight: 6 }}>INFO</span>
          {axisActionHint}
        </div>
      ) : null}
      {manualCalibrateHint ? (
        <div
          style={{ marginTop: 6, fontSize: 10, color: "rgba(180,220,255,0.92)" }}
          aria-live="polite"
        >
          <span style={{ ...vpHudPriorityBadgeStyle("info"), marginRight: 6 }}>INFO</span>
          {manualCalibrateHint}
        </div>
      ) : null}
      {isTauri() ? (
        <button
          type="button"
          onClick={onReturnAutoAxis}
          disabled={!canReturnAutoAxis}
          aria-label="Retornar para modo automático de eixo"
          title={
            canReturnAutoAxis
              ? undefined
              : "Disponível apenas quando axis_status=MANUAL_LOCKED."
          }
          style={{
            ...vpHudActionBtn,
            marginTop: 8,
            width: "100%",
            opacity: canReturnAutoAxis ? 1 : 0.5,
            cursor: canReturnAutoAxis ? "pointer" : "not-allowed",
          }}
        >
          Voltar para eixo automático
        </button>
      ) : null}
      {isTauri() ? (
        <button
          type="button"
          onClick={onCloseOverlay}
          aria-label="Fechar overlay"
          style={{
            ...vpHudActionBtn,
            marginTop: 8,
            width: "100%",
            border: "1px solid rgba(248,113,113,0.55)",
            background: "rgba(248,113,113,0.12)",
            color: "rgba(254,202,202,0.98)",
          }}
        >
          Fechar overlay
        </button>
      ) : null}
        </>
      ) : null}
    </div>
  );
}

const vpHudRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 4,
  cursor: "pointer",
  userSelect: "none",
};

const vpHudNumStyle: CSSProperties = {
  width: 56,
  padding: "2px 4px",
  fontSize: 11,
  borderRadius: 3,
  border: "1px solid rgba(255,255,255,0.2)",
  background: "rgba(0,0,0,0.35)",
  color: "inherit",
};

const vpHudActionBtn: CSSProperties = {
  flex: 1,
  padding: "6px 8px",
  fontSize: 10,
  fontWeight: 700,
  cursor: "pointer",
  borderRadius: 4,
  border: "1px solid rgba(255,255,255,0.25)",
  background: "rgba(0,0,0,0.45)",
  color: "rgba(235,240,248,0.95)",
};

function vpHudPriorityBadgeStyle(priority: "error" | "alert" | "info"): CSSProperties {
  if (priority === "error") {
    return {
      border: "1px solid rgba(248,113,113,0.7)",
      background: "rgba(127,29,29,0.4)",
      color: "rgba(254,202,202,0.98)",
      borderRadius: 999,
      padding: "1px 6px",
      fontSize: 9,
      fontWeight: 800,
      letterSpacing: "0.03em",
    };
  }
  if (priority === "alert") {
    return {
      border: "1px solid rgba(251,191,36,0.68)",
      background: "rgba(113,63,18,0.35)",
      color: "rgba(253,230,138,0.98)",
      borderRadius: 999,
      padding: "1px 6px",
      fontSize: 9,
      fontWeight: 800,
      letterSpacing: "0.03em",
    };
  }
  return {
    border: "1px solid rgba(125,211,252,0.62)",
    background: "rgba(12,74,110,0.32)",
    color: "rgba(186,230,253,0.98)",
    borderRadius: 999,
    padding: "1px 6px",
    fontSize: 9,
    fontWeight: 800,
    letterSpacing: "0.03em",
  };
}

function OverlayLineEl({
  line,
  rightMarginPx,
  vpProfileLeft,
}: {
  line: PositionedOverlayLine;
  rightMarginPx: number;
  /** Com VP Sato: linhas/labels ficam à esquerda do histograma, sem sobrepor. */
  vpProfileLeft?: number | null;
}) {
  const { value, y_screen, color, chart_left, chart_right, label: paramLabel, labelY, rank, dense } =
    line;
  const compact = dense;
  const labelH = compact ? 32 : LABEL_H;
  const titleFontSize = compact ? 9 : 10;
  const priceFontSize = compact ? 11 : 12;

  const priceStr =
    value >= 1000 || value <= -1000
      ? value.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
      : value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const defaultLineRight = Math.max(
    chart_left + LABEL_W + 24,
    chart_right - rightMarginPx - OVERLAY_LINE_LEFT_SHIFT_PX,
  );
  const metricLeftLayout =
    vpProfileLeft != null && Number.isFinite(vpProfileLeft) && vpProfileLeft > chart_left + LABEL_W + 40;
  const lineRight = metricLeftLayout
    ? Math.min(defaultLineRight, Math.max(chart_left + LABEL_W + 32, vpProfileLeft - METRIC_LINE_VP_GAP_PX))
    : defaultLineRight;
  const metricLaneW = metricLeftLayout ? lineRight - chart_left : 0;
  const metricLabelCentered =
    metricLeftLayout && metricLaneW >= LABEL_W + 16;
  const lx = metricLabelCentered
    ? chart_left + (metricLaneW - LABEL_W) / 2
    : metricLeftLayout
      ? chart_left + 6
      : lineRight - LABEL_W - 4;
  const ly = labelY - labelH / 2;
  const baseTitle = paramLabel?.trim() ? paramLabel.trim() : "";
  const title = baseTitle ? `${rank}) ${baseTitle}` : "";
  const labelTextX = metricLabelCentered
    ? lx + LABEL_W / 2
    : metricLeftLayout
      ? chart_left + 10
      : lineRight - 8;
  const textAnchor: "start" | "middle" | "end" = metricLabelCentered
    ? "middle"
    : metricLeftLayout
      ? "start"
      : "end";
  const connectorX2 = metricLeftLayout ? lx + LABEL_W + 2 : lx - 3;

  return (
    <g>
      <line
        x1={metricLeftLayout ? lineRight : lineRight - 14}
        y1={y_screen}
        x2={connectorX2}
        y2={labelY}
        stroke={color}
        strokeWidth={1}
        opacity={0.78}
      />
      <line
        x1={chart_left}
        y1={y_screen}
        x2={lineRight}
        y2={y_screen}
        stroke="rgba(0,0,0,0.5)"
        strokeWidth={3.5}
        strokeDasharray="10 5"
        opacity={0.4}
      />
      <line
        x1={chart_left}
        y1={y_screen}
        x2={lineRight}
        y2={y_screen}
        stroke={color}
        strokeWidth={1.8}
        strokeDasharray="10 5"
        opacity={0.92}
      />
      <rect
        x={lx}
        y={ly}
        width={LABEL_W}
        height={labelH}
        rx={3}
        fill="rgba(10,10,10,0.82)"
        stroke={color}
        strokeWidth={1}
      />
      {title ? (
        <text
          x={labelTextX}
          y={labelY - (compact ? 4 : 3)}
          fill="rgba(200,210,225,0.95)"
          fontSize={titleFontSize}
          fontFamily={FONT}
          fontWeight="600"
          textAnchor={textAnchor}
          style={{ letterSpacing: "0.02em" }}
        >
          {title}
        </text>
      ) : null}
      <text
        x={labelTextX}
        y={labelY + (title ? (compact ? 10 : 12) : 5)}
        fill={color}
        fontSize={priceFontSize}
        fontFamily={FONT}
        fontWeight="700"
        textAnchor={textAnchor}
        style={{ letterSpacing: "0.04em" }}
      >
        {priceStr}
      </text>
      <polygon
        points={`${chart_left},${y_screen - 5} ${chart_left + 10},${y_screen} ${chart_left},${y_screen + 5}`}
        fill={color}
        opacity={0.85}
      />
    </g>
  );
}

function VolumeProfileLayer({
  overlay,
  showHistogram,
}: {
  overlay: VolumeProfileOverlayModel;
  showHistogram: boolean;
}) {
  const chart = overlay.chart;
  const levelsSafe = Array.isArray(overlay.levels) ? overlay.levels : [];
  if (
    !chart ||
    !Number.isFinite(chart.left) ||
    !Number.isFinite(chart.top) ||
    !Number.isFinite(chart.right) ||
    !Number.isFinite(chart.bottom) ||
    !Number.isFinite(overlay.profileLeft) ||
    !Number.isFinite(overlay.profileRight)
  ) {
    return <g />;
  }
  const levelH = safePx(overlay.levelHeight, 2);
  const vaTop =
    overlay.vahY != null && overlay.valY != null && Number.isFinite(overlay.vahY) && Number.isFinite(overlay.valY)
      ? clamp(Math.min(overlay.vahY, overlay.valY), chart.top, chart.bottom)
      : null;
  const vaBottom =
    overlay.vahY != null && overlay.valY != null && Number.isFinite(overlay.vahY) && Number.isFinite(overlay.valY)
      ? clamp(Math.max(overlay.vahY, overlay.valY), chart.top, chart.bottom)
      : null;
  const vaWidth = Math.max(0, safeNumber(overlay.profileRight - chart.left, 0));

  return (
    <g>
      {vaTop != null && vaBottom != null && vaBottom > vaTop ? (
        <rect
          x={chart.left}
          y={vaTop}
          width={vaWidth}
          height={Math.max(0, vaBottom - vaTop)}
          fill="rgba(168,85,247,0.035)"
        />
      ) : null}
      <line
        x1={overlay.profileLeft}
        y1={chart.top}
        x2={overlay.profileLeft}
        y2={chart.bottom}
        stroke="rgba(239,68,68,0.72)"
        strokeWidth={safePx(2, 2)}
      />
      {showHistogram
        ? levelsSafe.map((level) => {
            const y = clamp(safeNumber(level.y, chart.top), chart.top, chart.bottom);
            const lvlW = Math.max(0, safeNumber(level.width, 0));
            const x2 = safeNumber(
              Math.min(overlay.profileRight, overlay.profileLeft + lvlW),
              overlay.profileLeft,
            );
            const color = volumeProfileLevelColor(level, overlay.poc);
            const strikeBack = safePx(levelH + 1.2, 2);
            const strikeFront = safePx(levelH, 1.25);
            return (
              <g key={`${level.price}-${Math.round(level.y)}`}>
                <line
                  x1={overlay.profileLeft}
                  y1={y}
                  x2={x2}
                  y2={y}
                  stroke="rgba(0,0,0,0.55)"
                  strokeWidth={strikeBack}
                />
                <line
                  x1={overlay.profileLeft}
                  y1={y}
                  x2={x2}
                  y2={y}
                  stroke={color}
                  strokeWidth={strikeFront}
                />
              </g>
            );
          })
        : null}
      <VolumeProfileLine
        y={overlay.pocY}
        chart={chart}
        lineEndX={overlay.lineEndX}
        label="POC"
        price={overlay.poc}
        color="#FDBA74"
      />
      <VolumeProfileLine
        y={overlay.vahY}
        chart={chart}
        lineEndX={overlay.lineEndX}
        label="VAH"
        price={overlay.vah}
        color="#e53935"
        dashed
      />
      <VolumeProfileLine
        y={overlay.valY}
        chart={chart}
        lineEndX={overlay.lineEndX}
        label="VAL"
        price={overlay.val}
        color="#e53935"
        dashed
      />
      <rect
        x={overlay.profileLeft}
        y={chart.top + 6}
        width={safePx(Math.min(124, overlay.profileWidth), 48)}
        height={28}
        rx={2}
        fill="rgba(0,0,0,0.66)"
        stroke={overlay.ySource === "ocr" ? "rgba(255,255,255,0.12)" : "rgba(251,191,36,0.58)"}
      />
      <text
        x={overlay.profileLeft + 6}
        y={chart.top + 18}
        fill="rgba(255,255,255,0.94)"
        fontSize={10}
        fontFamily={FONT}
        fontWeight="800"
        style={{ letterSpacing: "0.12em" }}
      >
        VP SATO
      </text>
      <text
        x={overlay.profileLeft + 6}
        y={chart.top + 30}
        fill={overlay.ySource === "ocr" ? "rgba(255,255,255,0.62)" : "rgba(253,230,138,0.92)"}
        fontSize={9}
        fontFamily={FONT}
      >
        {overlay.period} · {formatCompactVol(overlay.totalVol)}{overlay.ySource === "ocr" ? "" : " · fallback"}
      </text>
      <text
        x={overlay.profileLeft + 6}
        y={chart.top + 40}
        fill="rgba(255,255,255,0.48)"
        fontSize={8}
        fontFamily={FONT}
      >
        {`vis ${levelsSafe.length} · merge ${overlay.histogramCoalesced ?? 0}`}
      </text>
    </g>
  );
}

function VolumeProfileLine({
  y,
  chart,
  lineEndX,
  label,
  price,
  color,
  dashed = false,
}: {
  y: number | null;
  chart: ScaledChartRect;
  lineEndX: number;
  label: string;
  price: number;
  color: string;
  dashed?: boolean;
}) {
  if (y == null || !Number.isFinite(y) || y < chart.top || y > chart.bottom) return null;
  const yDraw = safeNumber(y, chart.top + chart.height / 2);
  const labelW = 96;
  const labelX = safeNumber(Math.max(chart.left + 4, lineEndX - labelW - 4), chart.left + 4);
  const lx1 = safeNumber(chart.left, 0);
  const lx2 = safeNumber(lineEndX, lx1 + 80);
  return (
    <g>
      <line
        x1={lx1}
        y1={yDraw}
        x2={lx2}
        y2={yDraw}
        stroke="rgba(0,0,0,0.55)"
        strokeWidth={safePx(3.2, 3)}
        strokeDasharray={dashed ? "7 5" : undefined}
      />
      <line
        x1={lx1}
        y1={yDraw}
        x2={lx2}
        y2={yDraw}
        stroke={color}
        strokeWidth={safePx(1.6, 1.5)}
        strokeDasharray={dashed ? "7 5" : undefined}
      />
      <rect
        x={labelX}
        y={safeNumber(yDraw - 11, chart.top)}
        width={labelW}
        height={22}
        rx={2}
        fill="rgba(0,0,0,0.70)"
        stroke={color}
        strokeWidth={safePx(1, 1)}
      />
      <text
        x={labelX + 6}
        y={safeNumber(yDraw + 5, yDraw)}
        fill={color}
        fontSize={11}
        fontFamily={FONT}
        fontWeight="800"
      >
        {label} {formatProfilePrice(safeNumber(price, 0))}
      </text>
    </g>
  );
}

function VolumeProfileWaitingBadge({
  chart,
  volumeProfile,
}: {
  chart: ScaledChartRect;
  volumeProfile: VolumeProfileMessage | null;
}) {
  const text = volumeProfile
    ? "VP SATO: aguardando eixo OCR"
    : "VP SATO: aguardando snapshot";
  return (
    <g>
      <rect
        x={chart.right - VP_WAITING_BADGE_W - 16}
        y={chart.top + 10}
        width={VP_WAITING_BADGE_W}
        height={28}
        rx={3}
        fill="rgba(0,0,0,0.62)"
        stroke="rgba(251,191,36,0.55)"
      />
      <text
        x={chart.right - VP_WAITING_BADGE_W - 6}
        y={chart.top + 29}
        fill="rgba(253,230,138,0.92)"
        fontSize={10}
        fontFamily={FONT}
        fontWeight="700"
      >
        {text}
      </text>
    </g>
  );
}

function TapeBadge({ badge }: { badge: TapeBadgeModel }) {
  const leader = Array.isArray(badge.top3) ? badge.top3[0] : undefined;
  const volText = leader ? formatCompactVol(leader.total_vol) : "";
  const who = brokerDisplayName(
    badge.player,
    badge.playerName ?? leader?.player_name,
  );
  const bx = safeNumber(badge.x, 0);
  const by = safeNumber(badge.y, 0);
  return (
    <g>
      <line
        x1={bx + 114}
        y1={by}
        x2={bx + 132}
        y2={by}
        stroke={badge.color}
        strokeWidth={safePx(1, 1)}
        opacity={0.75}
      />
      <rect
        x={bx}
        y={safeNumber(by - 10, 0)}
        width={116}
        height={20}
        rx={3}
        fill="rgba(0,0,0,0.72)"
        stroke={badge.color}
        strokeWidth={1}
      />
      <text
        x={bx + 6}
        y={safeNumber(by + 4, by)}
        fill={badge.color}
        fontSize={10}
        fontFamily={FONT}
        fontWeight="800"
      >
        {badge.label} {who}
        {badge.side ? ` ${badge.side}` : ""}
      </text>
      {volText ? (
        <text
          x={bx + 110}
          y={safeNumber(by + 4, by)}
          fill="rgba(255,255,255,0.70)"
          fontSize={9}
          fontFamily={FONT}
          fontWeight="700"
          textAnchor="end"
        >
          {volText}
        </text>
      ) : null}
    </g>
  );
}

function StatusBadge({
  status,
  overlayGuard,
  y_min,
  y_max,
  axis_deltas,
  axis_diagnostics,
  alignmentMaxDeltaPx,
  viewportHeight,
  visibleLineCount,
  visibleHistogramLevels,
  histogramCandidates,
  histogramRendered,
  histogramCoalesced,
  avgLineVisibleCount,
  avgLineCandidates,
  labelCollisionsCount,
  overlayCommitMs,
  overlayCommitHz,
  axisStatus,
  axisSource,
  badFrames,
  axisErrorCode,
  axisErrorMessage,
  lastGoodAxisAgeMs,
  overlayWindowAlive,
  ocrServiceAlive,
  ocrWsConnected,
  vpStatus,
  lineStatusSummary,
  rawAxisStatus,
  normalizedAxisStatus,
  fallbackReason,
  payloadSeq,
  wsUrl,
  ocrPid,
  ocrPort,
  parsedLabelsCount,
  ocrConfidence,
  lastPayloadAgeMs,
  axisCaptureInitial,
  axisCaptureCurrent,
}: {
  status: string;
  overlayGuard?: string | null;
  y_min: number | null;
  y_max: number | null;
  axis_deltas?: OcrAxisDeltasOrLegacy | null;
  axis_diagnostics?: {
    raw_labels?: number;
    kept_labels?: number;
    rejected?: number;
  } | null;
  alignmentMaxDeltaPx: number | null;
  viewportHeight: number;
  visibleLineCount: number;
  visibleHistogramLevels: number;
  histogramCandidates: number;
  histogramRendered: number;
  histogramCoalesced: number;
  avgLineVisibleCount: number;
  avgLineCandidates: number;
  labelCollisionsCount: number;
  overlayCommitMs: number;
  overlayCommitHz: number;
  axisStatus: string | null;
  axisSource: string | null;
  badFrames: number | null;
  axisErrorCode: string | null;
  axisErrorMessage: string | null;
  lastGoodAxisAgeMs: number | null;
  overlayWindowAlive: boolean | null;
  ocrServiceAlive: boolean | null;
  ocrWsConnected: boolean | null;
  vpStatus: string | null;
  lineStatusSummary: string;
  rawAxisStatus: string | null;
  normalizedAxisStatus: string | null;
  fallbackReason: string | null;
  payloadSeq: number | null;
  wsUrl: string | null;
  ocrPid: number | null;
  ocrPort: number | null;
  parsedLabelsCount: number | null;
  ocrConfidence: number | null;
  lastPayloadAgeMs: number | null;
  axisCaptureInitial?: string | null;
  axisCaptureCurrent?: string | null;
}) {
  const color = overlayStatusColor(status);
  const text = overlayStatusText(status, y_min, y_max, axis_deltas);
  const diagText =
    axis_diagnostics && typeof axis_diagnostics.kept_labels === "number"
      ? `labels ${axis_diagnostics.kept_labels}/${axis_diagnostics.raw_labels ?? "?"} | rej ${axis_diagnostics.rejected ?? 0}`
      : "";
  const vpDbg =
    histogramCandidates > 0
      ? `hist ${histogramRendered}/${histogramCandidates} vis ${visibleHistogramLevels}`
      : "";
  const histCoalDbg =
    histogramCoalesced > 0 ? `hist merge ${histogramCoalesced}` : "";
  const lineDbg =
    visibleLineCount > 0 ? `ocr ${visibleLineCount} vis` : "";
  const avgDbg =
    avgLineCandidates > 0
      ? `mon ${avgLineVisibleCount}/${avgLineCandidates} vis`
      : "";
  const collDbg =
    labelCollisionsCount > 0 ? `lbl≈coll ${labelCollisionsCount}` : "";
  const alignDbg =
    alignmentMaxDeltaPx != null ? `align ${Math.round(alignmentMaxDeltaPx)}px` : "";
  const perfDbg =
    overlayCommitMs > 0 && overlayCommitHz > 0
      ? `render ${overlayCommitMs}ms ~${overlayCommitHz}Hz`
      : "";
  const axisDbg = axisStatus
    ? `axis ${axisStatus}${axisSource ? `/${axisSource}` : ""}${badFrames != null ? ` bf:${badFrames}` : ""}`
    : "";
  const axisRawDbg = rawAxisStatus ? `raw_axis ${rawAxisStatus}` : "";
  const axisNormDbg = normalizedAxisStatus ? `norm_axis ${normalizedAxisStatus}` : "";
  const axisErrDbg = axisErrorCode
    ? `axis_err ${axisErrorCode}${axisErrorMessage ? ` (${axisErrorMessage})` : ""}`
    : "";
  const axisAgeDbg = lastGoodAxisAgeMs != null ? `last_good ${Math.round(lastGoodAxisAgeMs)}ms` : "";
  const payloadDbg = payloadSeq != null ? `seq ${Math.round(payloadSeq)}` : "";
  const labelsDbg = parsedLabelsCount != null ? `labels_parsed ${parsedLabelsCount}` : "";
  const confDbg = ocrConfidence != null ? `ocr_conf ${Math.round(ocrConfidence * 1000) / 1000}` : "";
  const fallbackDbg = fallbackReason ? `fallback ${fallbackReason}` : "";
  const wsDbg = wsUrl ? `ws_url ${wsUrl}` : "";
  const pidDbg = ocrPid != null ? `ocr_pid ${Math.round(ocrPid)}` : "";
  const portDbg = ocrPort != null ? `ocr_port ${Math.round(ocrPort)}` : "";
  const payloadAgeDbg =
    lastPayloadAgeMs != null ? `payload_age ${Math.round(lastPayloadAgeMs)}ms` : "";
  const healthDbg = [
    overlayWindowAlive != null ? `win ${overlayWindowAlive ? "alive" : "down"}` : "",
    ocrServiceAlive != null ? `ocr ${ocrServiceAlive ? "alive" : "down"}` : "",
    ocrWsConnected != null ? `ws ${ocrWsConnected ? "connected" : "disconnected"}` : "",
    vpStatus ? `vp ${vpStatus}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const linesDbg = lineStatusSummary ? `lines ${lineStatusSummary}` : "";
  const guardDbg = overlayGuard ? `guard ${overlayGuard}` : "";
  const axisCapIni = axisCaptureInitial?.trim() || "";
  const axisCapNow = axisCaptureCurrent?.trim() || "";
  const axisCapDbg =
    axisCapIni || axisCapNow
      ? [axisCapIni, axisCapNow].filter(Boolean).join(" · ")
      : "";
  const frozenHint =
    rawAxisStatus &&
    (rawAxisStatus.toUpperCase() === "FROZEN" || rawAxisStatus.toUpperCase() === "MANUAL_LOCKED")
      ? "eixo congelado — Recalibrar/Descongelar após mover escala no Profit"
      : "";
  const vh = safeNumber(viewportHeight, 400);
  const badgeH = axisCapDbg || frozenHint ? 68 : 36;
  const badgeY = safeNumber(vh - badgeH - 8, 8);

  return (
    <g>
      <rect
        x={8}
        y={badgeY}
        width={safeNumber(1180, 400)}
        height={badgeH}
        rx={3}
        fill="rgba(0,0,0,0.65)"
      />
      <text
        x={14}
        y={badgeY + 14}
        fill={color}
        fontSize={11}
        fontFamily={FONT}
        fontWeight="600"
      >
        {text}
      </text>
      {frozenHint ? (
        <text
          x={14}
          y={badgeY + 28}
          fill="rgba(251,191,36,0.95)"
          fontSize={10}
          fontFamily={FONT}
          fontWeight="600"
        >
          {frozenHint}
        </text>
      ) : null}
      {axisCapDbg ? (
        <text
          x={14}
          y={badgeY + (frozenHint ? 42 : 28)}
          fill="rgba(147,197,253,0.92)"
          fontSize={9}
          fontFamily={FONT}
          fontWeight="500"
        >
          {axisCapDbg}
        </text>
      ) : null}
      {diagText ? (
        <text
          x={14}
          y={badgeY + badgeH - 8}
          fill="rgba(210,220,230,0.86)"
          fontSize={10}
          fontFamily={FONT}
          fontWeight="500"
        >
          {[diagText, alignDbg, lineDbg, vpDbg, histCoalDbg, avgDbg, collDbg, perfDbg]
            .concat([
              axisDbg,
              axisRawDbg,
              axisNormDbg,
              axisErrDbg,
              axisAgeDbg,
              labelsDbg,
              confDbg,
              payloadDbg,
              payloadAgeDbg,
              pidDbg,
              portDbg,
              wsDbg,
              fallbackDbg,
              healthDbg,
              linesDbg,
              guardDbg,
            ])
            .filter(Boolean)
            .join(" · ")}
        </text>
      ) : lineDbg || vpDbg || histCoalDbg || avgDbg || collDbg || alignDbg || perfDbg || guardDbg ? (
        <text
          x={14}
          y={badgeY + badgeH - 8}
          fill="rgba(210,220,230,0.86)"
          fontSize={10}
          fontFamily={FONT}
          fontWeight="500"
        >
          {[
            alignDbg,
            lineDbg,
            vpDbg,
            histCoalDbg,
            avgDbg,
            collDbg,
            perfDbg,
            axisDbg,
            axisRawDbg,
            axisNormDbg,
            axisErrDbg,
            axisAgeDbg,
            labelsDbg,
            confDbg,
            payloadDbg,
            payloadAgeDbg,
            pidDbg,
            portDbg,
            wsDbg,
            fallbackDbg,
            healthDbg,
            linesDbg,
            guardDbg,
          ]
            .filter(Boolean)
            .join(" · ")}
        </text>
      ) : null}
    </g>
  );
}
