import type { OcrAxisDeltas, OcrAxisDeltasOrLegacy } from "./ocrStatus";

type UnknownRecord = Record<string, unknown>;

export interface OverlayCompatLine {
  value: number;
  y_screen: number;
  color: string;
  chart_left: number;
  chart_right: number;
  label?: string;
  status?: string;
  out_of_bounds?: boolean;
  line_id?: string;
  y_chart?: number;
  frame_axis_id?: number;
  axis_source?: string;
}

export interface OverlayUpdateCompatPayload {
  rawMessage: UnknownRecord;
  rawData: UnknownRecord;
  status: string;
  lines: OverlayCompatLine[];
  yMin: number | null;
  yMax: number | null;
  axisDeltas: OcrAxisDeltasOrLegacy | null;
  axisDiagnostics: Record<string, unknown> | null;
  analysisRoi: Record<string, unknown> | null;
  analysisSample: Record<string, unknown> | null;
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
  debugVisual: Record<string, unknown> | null;
  normalizedAxisStatus: string | null;
  parsedLabelsCount: number | null;
  ocrConfidence: number | null;
  payloadSeq: number | null;
  ocrPid: number | null;
  ocrPort: number | null;
  geometry: UnknownRecord | null;
  axisFit: UnknownRecord | null;
  axisId: number | null;
  axisSamples: unknown[] | null;
}

function asRecord(value: unknown): UnknownRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as UnknownRecord;
}

function asNumberOrNull(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function asStringOrNull(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return value;
}

function asBoolOrNull(value: unknown): boolean | null {
  if (typeof value !== "boolean") return null;
  return value;
}

function normalizeAxisStatus(value: unknown): string | null {
  const raw = asStringOrNull(value);
  if (!raw) return null;
  const v = raw.trim().toLowerCase();
  if (!v) return null;
  if (v === "stable") return "stable";
  if (v === "frozen" || v === "freeze" || v === "locked" || v === "paused") return "frozen";
  if (v === "suspect") return "suspect";
  if (v === "recalibrating") return "recalibrating";
  if (v === "no_axis" || v === "not_found" || v === "missing") return "no_axis";
  if (v === "geometry_mismatch" || v === "geometry_calibrating") return "geometry_calibrating";
  if (v === "manual_locked") return "manual_locked";
  if (v === "boot_from_cache") return "boot_from_cache";
  if (v === "boot_from_cache_degraded") return "boot_from_cache_degraded";
  if (v === "manual_stable") return "manual_stable";
  if (v === "ocr_validated") return "ocr_validated";
  if (v === "ocr_conflict") return "ocr_conflict";
  if (v === "needs_calibration") return "needs_calibration";
  return v;
}

function asAxisDeltas(value: unknown): OcrAxisDeltas | null {
  const row = asRecord(value);
  if (!row) return null;
  const deltaFirstLastValue = asNumberOrNull(row.delta_first_last_value);
  const deltaFirstLastY = asNumberOrNull(row.delta_first_last_y);
  const labelsCount = asNumberOrNull(row.labels_count);
  if (
    deltaFirstLastValue == null ||
    deltaFirstLastY == null ||
    labelsCount == null ||
    !Array.isArray(row.delta_intervals)
  ) {
    return null;
  }
  const deltaIntervals = row.delta_intervals
    .map((item) => {
      const interval = asRecord(item);
      if (!interval) return null;
      const i = asNumberOrNull(interval.i);
      const valueDelta = asNumberOrNull(interval.value_delta);
      const yDelta = asNumberOrNull(interval.y_delta);
      const valuePerPxSegment = asNumberOrNull(interval.value_per_px_segment);
      if (
        i == null ||
        valueDelta == null ||
        yDelta == null ||
        valuePerPxSegment == null
      ) {
        return null;
      }
      return {
        i,
        value_delta: valueDelta,
        y_delta: yDelta,
        value_per_px_segment: valuePerPxSegment,
      };
    })
    .filter((item): item is OcrAxisDeltas["delta_intervals"][number] => item != null);
  return {
    delta_first_last_value: deltaFirstLastValue,
    delta_first_last_y: deltaFirstLastY,
    delta_intervals: deltaIntervals,
    labels_count: labelsCount,
  };
}

/** Deltas no formato completo do OCR, ou objeto legado/arbitrário preservado para debug. */
function parseAxisDeltasCompat(value: unknown): OcrAxisDeltasOrLegacy | null {
  const strict = asAxisDeltas(value);
  if (strict) return strict;
  const row = asRecord(value);
  if (!row || Object.keys(row).length === 0) return null;
  return row;
}

export function parseOverlayUpdatePayload(message: unknown): OverlayUpdateCompatPayload | null {
  const envelope = asRecord(message);
  if (!envelope) return null;
  if (envelope.type !== "overlay_update") return null;

  const data = asRecord(envelope.data) ?? asRecord(envelope.payload) ?? {};
  const structured = asRecord(data.structured);
  const statusBlock = asRecord(data.status) ?? asRecord(structured?.status);
  const linesBlock = asRecord(data.lines) ?? asRecord(structured?.lines);
  const histogramBlock = asRecord(data.histogram) ?? asRecord(structured?.histogram);
  const axisBlock = asRecord(data.axis) ?? asRecord(structured?.axis);
  const geometryBlock = asRecord(data.geometry) ?? asRecord(structured?.geometry);
  const linesVisualLimits = asRecord(linesBlock?.visual_limits);
  const debugVisualBlock =
    asRecord(data.debug_visual) ?? asRecord(structured?.debug_visual);
  const axisSamplesRaw = debugVisualBlock
    ? (debugVisualBlock as { axis_samples?: unknown }).axis_samples
    : undefined;
  const axisSamples = Array.isArray(axisSamplesRaw) ? axisSamplesRaw : null;

  const lineItemsMaybe = Array.isArray(data.lines)
    ? data.lines
    : Array.isArray(linesBlock?.items)
      ? linesBlock.items
      : [];
  const lines = lineItemsMaybe.filter((line): line is OverlayCompatLine => {
    const row = asRecord(line);
    if (!row) return false;
    return (
      typeof row.value === "number" &&
      Number.isFinite(row.value) &&
      typeof row.y_screen === "number" &&
      Number.isFinite(row.y_screen) &&
      typeof row.color === "string" &&
      typeof row.chart_left === "number" &&
      Number.isFinite(row.chart_left) &&
      typeof row.chart_right === "number" &&
      Number.isFinite(row.chart_right)
    );
  }) as OverlayCompatLine[];

  const geometry = geometryBlock && Object.keys(geometryBlock).length > 0 ? geometryBlock : null;
  const axisFit =
    asRecord(data.axis_fit) ?? asRecord(axisBlock?.axis_fit) ?? null;
  const axisId =
    asNumberOrNull(data.axis_id) ?? asNumberOrNull(axisBlock?.axis_id);

  const statusLegacy = asStringOrNull(data.status);
  const statusStructured = asStringOrNull(statusBlock?.state);
  const status = statusLegacy ?? statusStructured ?? "";

  const yMin =
    asNumberOrNull(data.y_min) ?? asNumberOrNull(linesVisualLimits?.y_min);
  const yMax =
    asNumberOrNull(data.y_max) ?? asNumberOrNull(linesVisualLimits?.y_max);

  const axisStatus =
    asStringOrNull(data.axis_status) ?? asStringOrNull(axisBlock?.axis_status);
  const axisSource =
    asStringOrNull(data.axis_source) ?? asStringOrNull(axisBlock?.axis_source);
  const badFrames =
    asNumberOrNull(data.bad_frames) ?? asNumberOrNull(axisBlock?.bad_frames);
  const axisErrorCode =
    asStringOrNull(data.axis_error_code) ?? asStringOrNull(axisBlock?.axis_error_code);
  const axisErrorMessage =
    asStringOrNull(data.axis_error_message) ?? asStringOrNull(axisBlock?.axis_error_message);
  const lastGoodAxisAgeMs =
    asNumberOrNull(data.last_good_axis_age_ms) ??
    asNumberOrNull(axisBlock?.last_good_axis_age_ms);
  const overlayWindowAlive =
    asBoolOrNull(data.overlay_window_alive) ??
    asBoolOrNull(statusBlock?.overlay_window_alive);
  const ocrServiceAlive =
    asBoolOrNull(data.ocr_service_alive) ??
    asBoolOrNull(statusBlock?.ocr_service_alive);
  const ocrWsConnected =
    asBoolOrNull(data.ocr_ws_connected) ??
    asBoolOrNull(statusBlock?.ocr_ws_connected);
  const vpStatus = asStringOrNull(data.vp_status) ?? asStringOrNull(statusBlock?.vp_status);
  const normalizedAxisStatus = normalizeAxisStatus(
    asStringOrNull(data.axis_status) ?? asStringOrNull(axisBlock?.axis_status),
  );
  const parsedLabelsCount =
    asNumberOrNull(data.parsed_labels_count) ??
    asNumberOrNull(axisBlock?.labels_count) ??
    (Array.isArray(axisBlock?.axis_labels)
      ? axisBlock.axis_labels.length
      : Array.isArray(data.parsed_labels)
        ? data.parsed_labels.length
        : null);
  const ocrConfidence = asNumberOrNull(data.ocr_confidence) ?? asNumberOrNull(axisBlock?.confidence);
  const payloadSeq =
    asNumberOrNull(data.frame_seq) ??
    asNumberOrNull(envelope.seq) ??
    asNumberOrNull(asRecord(envelope.meta)?.frame_seq) ??
    asNumberOrNull(asRecord(data.last_frame)?.seq);
  const ocrPid = asNumberOrNull(data.ocr_pid) ?? asNumberOrNull(asRecord(envelope.meta)?.ocr_pid);
  const ocrPort = asNumberOrNull(data.ocr_port) ?? asNumberOrNull(asRecord(envelope.meta)?.ocr_port);

  const analysisRoi =
    asRecord(data.analysis_roi) ?? asRecord(statusBlock?.analysis_roi);
  const analysisSample =
    asRecord(data.analysis_sample) ?? asRecord(statusBlock?.analysis_sample);

  const result = {
    rawMessage: envelope,
    rawData: data,
    status,
    lines,
    yMin,
    yMax,
    axisDeltas:
      parseAxisDeltasCompat(data.axis_deltas) ?? parseAxisDeltasCompat(histogramBlock?.axis_deltas),
    axisDiagnostics:
      asRecord(data.axis_diagnostics) ?? asRecord(histogramBlock?.axis_diagnostics),
    analysisRoi,
    analysisSample,
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
    debugVisual: debugVisualBlock,
    normalizedAxisStatus,
    parsedLabelsCount,
    ocrConfidence,
    payloadSeq,
    ocrPid,
    ocrPort,
    geometry,
    axisFit,
    axisId,
    axisSamples,
  };

  return result;
}
