import type { OcrAxisDeltas } from "./ocrStatus";

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
}

export interface OverlayUpdateCompatPayload {
  rawData: UnknownRecord;
  status: string;
  lines: OverlayCompatLine[];
  yMin: number | null;
  yMax: number | null;
  confidence: number | null;
  axisDeltas: OcrAxisDeltas | null;
  axisDiagnostics: Record<string, unknown> | null;
  analysisRoi: Record<string, unknown> | null;
  analysisSample: Record<string, unknown> | null;
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
  debugVisual: Record<string, unknown> | null;
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

export function parseOverlayUpdatePayload(message: unknown): OverlayUpdateCompatPayload | null {
  const envelope = asRecord(message);
  if (!envelope) return null;
  const envelopeType = asStringOrNull(envelope.type);
  const hasCompatTopLevelFields =
    "status" in envelope ||
    "lines" in envelope ||
    "structured" in envelope ||
    "blocks" in envelope ||
    "axis_status" in envelope;
  if (envelopeType != null && envelopeType !== "overlay_update") return null;
  if (envelopeType == null && !hasCompatTopLevelFields) return null;

  const data =
    asRecord(envelope.data) ??
    asRecord(envelope.payload) ??
    (envelopeType == null ? envelope : {});
  const blocks = asRecord(data.blocks);
  const structured = asRecord(data.structured) ?? blocks;
  const statusBlock = asRecord(data.status) ?? asRecord(structured?.status);
  const linesBlock =
    asRecord(data.lines) ?? asRecord(structured?.lines) ?? asRecord(blocks?.lines);
  const histogramBlock =
    asRecord(data.histogram) ??
    asRecord(structured?.histogram) ??
    asRecord(blocks?.histogram);
  const axisBlock =
    asRecord(data.axis) ?? asRecord(structured?.axis) ?? asRecord(blocks?.axis);
  const linesVisualLimits = asRecord(linesBlock?.visual_limits);
  const debugVisualBlock =
    asRecord(data.debug_visual) ?? asRecord(structured?.debug_visual);

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
  });

  const statusLegacy = asStringOrNull(data.status);
  const statusStructured = asStringOrNull(statusBlock?.state);
  const status = statusLegacy ?? statusStructured ?? "";

  const yMin =
    asNumberOrNull(data.y_min) ?? asNumberOrNull(linesVisualLimits?.y_min);
  const yMax =
    asNumberOrNull(data.y_max) ?? asNumberOrNull(linesVisualLimits?.y_max);

  const axisStatus =
    asStringOrNull(data.axis_status) ??
    asStringOrNull(axisBlock?.axis_status);
  const axisSource =
    asStringOrNull(data.axis_source) ??
    asStringOrNull(data.source) ??
    asStringOrNull(axisBlock?.axis_source) ??
    asStringOrNull(axisBlock?.source);
  const confidence =
    asNumberOrNull(data.confidence) ?? asNumberOrNull(axisBlock?.confidence);
  const badFrames =
    asNumberOrNull(data.bad_frames) ?? asNumberOrNull(axisBlock?.bad_frames);
  const pendingFrames =
    asNumberOrNull(data.pending_count) ??
    asNumberOrNull(data.pending_frames) ??
    asNumberOrNull(axisBlock?.pending_count) ??
    asNumberOrNull(axisBlock?.pending_frames);
  const labelsCount =
    asNumberOrNull(data.labels_count) ??
    asNumberOrNull(axisBlock?.labels_count) ??
    asNumberOrNull(data.axis_diagnostics && asRecord(data.axis_diagnostics)?.labels_count);
  const residualPx =
    asNumberOrNull(data.residual_px) ??
    asNumberOrNull(axisBlock?.residual_px) ??
    asNumberOrNull(data.axis_diagnostics && asRecord(data.axis_diagnostics)?.residual_px);
  const maxErrorPx =
    asNumberOrNull(data.max_error_px) ??
    asNumberOrNull(axisBlock?.max_error_px) ??
    asNumberOrNull(data.axis_diagnostics && asRecord(data.axis_diagnostics)?.max_error_px);
  const slope =
    asNumberOrNull(data.slope) ??
    asNumberOrNull(axisBlock?.slope) ??
    asNumberOrNull(debugVisualBlock && asRecord(debugVisualBlock.regression)?.slope);
  const intercept =
    asNumberOrNull(data.intercept) ??
    asNumberOrNull(axisBlock?.intercept) ??
    asNumberOrNull(debugVisualBlock && asRecord(debugVisualBlock.regression)?.intercept);
  const valuePerPx =
    asNumberOrNull(data.value_per_px) ??
    asNumberOrNull(axisBlock?.value_per_px) ??
    asNumberOrNull(debugVisualBlock && asRecord(debugVisualBlock.regression)?.value_per_px);

  const analysisRoi =
    asRecord(data.analysis_roi) ?? asRecord(statusBlock?.analysis_roi);
  const analysisSample =
    asRecord(data.analysis_sample) ?? asRecord(statusBlock?.analysis_sample);

  return {
    rawData: data,
    status,
    lines,
    yMin,
    yMax,
    confidence,
    axisDeltas:
      asAxisDeltas(data.axis_deltas) ?? asAxisDeltas(histogramBlock?.axis_deltas),
    axisDiagnostics:
      asRecord(data.axis_diagnostics) ?? asRecord(histogramBlock?.axis_diagnostics),
    analysisRoi,
    analysisSample,
    axisStatus,
    axisSource,
    badFrames,
    pendingFrames,
    labelsCount,
    residualPx,
    maxErrorPx,
    slope,
    intercept,
    valuePerPx,
    debugVisual: debugVisualBlock,
  };
}
