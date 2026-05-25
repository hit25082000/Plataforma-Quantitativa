import type {
  TapeIntelligenceMessage,
  VolumeProfileLevel,
  VolumeProfileMessage,
} from "../types/messages";
import {
  computeEffectiveYRange,
  computeVolumeProfileOverlayModel,
  fallbackChartRectForVp,
  overlayLineYCss,
  overlayPhysXToCss,
  scaleChartRect,
  volumeProfilePriceRange,
} from "./chartGeom";
import { computeTapeBadges } from "./computeTapeBadges";
import {
  filterOverlayLinesForVpMode,
  filterOverlayLinesWithoutVp,
} from "./filterMetricOverlayLines";
import { layoutOverlayLines } from "./layoutLegacyLines";
import type { OverlayDiagFlags } from "./overlayDiagEnv";
import { readOverlayDiagEnv } from "./overlayDiagEnv";
import type {
  BuildOverlayFrameResult,
  ChartRect,
  OverlayAxisLabelSample,
  OverlayGeometryPayload,
  OverlayLayoutSnapshot,
  OverlayLine,
  OverlayRenderFrame,
} from "./overlayFrameTypes";
import { isFiniteChartRect, isOverlayWindowRenderable } from "./overlayViewportGuards";

function fakeAxisOverlay(): Pick<
  OverlayLayoutSnapshot["data"],
  "lines" | "chart_rect" | "y_min" | "y_max" | "axis_status" | "normalized_axis_status" | "parsed_labels_count" | "last_good_axis_age_ms"
> {
  const chart_rect: ChartRect = { left: 120, top: 140, width: 880, height: 420 };
  const y_min = 10_000;
  const y_max = 50_000;
  const midY = chart_rect.top + chart_rect.height / 2;
  const lines: OverlayLine[] = [
    {
      value: 30_000,
      y_screen: midY,
      color: "#38bdf8",
      chart_left: chart_rect.left,
      chart_right: chart_rect.left + chart_rect.width,
      label: "FAKE",
      status: "stable",
    },
  ];
  return {
    lines,
    chart_rect,
    y_min,
    y_max,
    axis_status: "stable",
    normalized_axis_status: "stable",
    parsed_labels_count: 12,
    last_good_axis_age_ms: 0,
  };
}

/** Price ladder only; explicit `y` left unset so VP layer maps via chart + y-range. */
function fakeVolumeProfileMessage(): VolumeProfileMessage {
  const levels: VolumeProfileLevel[] = [];
  for (let i = -6; i <= 6; i++) {
    const price = 30_000 + i * 25;
    const tv = 1200 - Math.abs(i) * 80;
    levels.push({
      price,
      total_vol: tv,
      bid_vol: 400,
      ask_vol: 400,
      pct_of_max: tv / 1200,
    });
  }
  return {
    topic: "market",
    type: "volume_profile",
    ticker: "FAKE",
    period: "day",
    timestamp: Date.now(),
    poc: 30_000,
    vah: 30_150,
    val: 29_850,
    total_vol: 50000,
    price_step: 5,
    levels,
  };
}

function volumeProfileFromOcrAxisSamples(samples: OverlayAxisLabelSample[]): VolumeProfileMessage | null {
  const prices = samples.map((s) => Number(s.value)).filter((p) => Number.isFinite(p));
  if (prices.length === 0) return null;
  const sorted = [...prices].sort((a, b) => a - b);
  const poc = sorted[Math.floor(sorted.length / 2)]!;
  const val = sorted[0]!;
  const vah = sorted[sorted.length - 1]!;
  const stepRaw = sorted.length > 1 ? Math.abs(sorted[1]! - sorted[0]!) : 1;
  const price_step = Number.isFinite(stepRaw) && stepRaw > 0 ? stepRaw : 1;
  const levels: VolumeProfileLevel[] = sorted.map((price) => ({
    price,
    total_vol: 1000,
    bid_vol: 400,
    ask_vol: 400,
    pct_of_max: 1,
  }));
  return {
    topic: "market",
    type: "volume_profile",
    ticker: "OCR_LABELS",
    period: "day",
    timestamp: Date.now(),
    poc,
    vah,
    val,
    total_vol: 1000 * levels.length,
    price_step,
    levels,
  };
}

function fakeTapeIntelligence(vp: VolumeProfileMessage): TapeIntelligenceMessage {
  return {
    topic: "market",
    type: "tape_intelligence",
    timestamp: Date.now(),
    ticker: vp.ticker ?? "FAKE",
    poc_price: vp.poc,
    val_price: vp.val,
    vah_price: vp.vah,
    poc_player: 0,
    poc_player_name: "",
    val_buyer: 0,
    val_buyer_name: "",
    vah_seller: 0,
    vah_seller_name: "",
    poc_top3: [],
    val_top3: [],
    vah_top3: [],
    poc_y: vp.poc_y,
    val_y: vp.val_y,
    vah_y: vp.vah_y,
  };
}

function countRenderItems(frame: OverlayRenderFrame): number {
  let n = frame.positionedLines.length + frame.tapeBadges.length;
  if (frame.volumeProfileOverlay) n += frame.volumeProfileOverlay.levels.length;
  return n;
}

/**
 * Pure layout/frame build for Profit overlay (SVG). Wrapped in try/catch by callers.
 */
export function buildOverlayFrame(
  snapshot: OverlayLayoutSnapshot,
  diagOverride?: OverlayDiagFlags | null,
): BuildOverlayFrameResult {
  const diag = diagOverride ?? readOverlayDiagEnv();
  const data = { ...snapshot.data };
  data.lines = Array.isArray(data.lines) ? data.lines : [];
  let volumeProfile = snapshot.volumeProfile;
  let tapeIntelligence = snapshot.tapeIntelligence;

  if (diag.axisMode === "fake") {
    Object.assign(data, fakeAxisOverlay());
  }

  const W = snapshot.viewportWidth;
  const H = snapshot.viewportHeight;
  const dpr = snapshot.devicePixelRatio;
  if (!isOverlayWindowRenderable({ width: W, height: H, devicePixelRatio: dpr })) {
    return { frame: null, renderItemsCount: 0, error: null, viewportInvalid: true };
  }

  const renderScale = 1 / dpr;
  const axisUsable = snapshot.axisUsableForOcr || diag.axisMode === "fake";
  const scaledChartRect = axisUsable ? scaleChartRect(data.chart_rect, renderScale) : null;
  let vpRange = volumeProfilePriceRange(volumeProfile);
  const fallbackVpChartRect =
    volumeProfile && !scaledChartRect ? fallbackChartRectForVp(W, H) : null;
  let effectiveChartRect = scaledChartRect ?? fallbackVpChartRect;

  if (diag.vpMode === "fake" && volumeProfile == null) {
    volumeProfile = fakeVolumeProfileMessage();
    tapeIntelligence = fakeTapeIntelligence(volumeProfile);
    vpRange = volumeProfilePriceRange(volumeProfile);
    if (!effectiveChartRect) {
      effectiveChartRect = fallbackChartRectForVp(W, H);
    }
  }

  if (diag.vpMode === "ocr_labels_fake") {
    const samples = (data.axis_samples ?? []) as OverlayAxisLabelSample[];
    const built = volumeProfileFromOcrAxisSamples(samples);
    if (built) {
      volumeProfile = built;
      tapeIntelligence = fakeTapeIntelligence(volumeProfile);
      vpRange = volumeProfilePriceRange(volumeProfile);
      if (!effectiveChartRect) {
        effectiveChartRect = fallbackChartRectForVp(W, H);
      }
    }
  }

  const manualCalibrationOk =
    (snapshot.vpFallbackMode || "auto").trim().toLowerCase() === "manual" &&
    typeof snapshot.manualTop === "number" &&
    typeof snapshot.manualBot === "number" &&
    Number.isFinite(snapshot.manualTop) &&
    Number.isFinite(snapshot.manualBot) &&
    snapshot.manualTop !== snapshot.manualBot;

  const { effectiveYMin, effectiveYMax, usingOcrChart } = computeEffectiveYRange({
    scaledChartRect,
    dataYMin: data.y_min,
    dataYMax: data.y_max,
    manualCalibrationOk,
    manualTop: snapshot.manualTop,
    manualBot: snapshot.manualBot,
    fallbackYLock: snapshot.fallbackYLock,
    vpRange,
  });

  const logicalChartRect: ChartRect | null = effectiveChartRect
    ? {
        left: effectiveChartRect.left / renderScale,
        top: effectiveChartRect.top / renderScale,
        width: effectiveChartRect.width / renderScale,
        height: effectiveChartRect.height / renderScale,
      }
    : data.chart_rect ?? null;

  let guardStatus: OverlayRenderFrame["guardStatus"] = "OK";
  if (!isFiniteChartRect(logicalChartRect)) {
    guardStatus = "DEGRADED";
  } else if (!axisUsable && snapshot.axisUnusableReason && diag.axisMode !== "fake") {
    guardStatus = "FROZEN";
  }

  const geom = (data.geometry ?? null) as OverlayGeometryPayload | null;
  const axisNorm = (data.normalized_axis_status ?? data.axis_status ?? "").trim().toLowerCase();
  const axisStableForIndicators =
    axisNorm === "stable" || axisNorm === "manual_locked" || axisNorm === "ocr_validated";
  const allowCanonicalProjection =
    axisStableForIndicators &&
    data.axis_fit != null &&
    typeof data.axis_fit.slope === "number" &&
    Number.isFinite(data.axis_fit.slope) &&
    geom?.overlay_rect_screen != null &&
    geom?.chart_rect_screen != null;
  const axisIdCurrent = data.axis_id ?? null;
  let linesForRender = data.lines.filter((ln) => {
    if (axisIdCurrent == null) return true;
    if (ln.frame_axis_id == null) return true;
    return ln.frame_axis_id === axisIdCurrent;
  });
  if (data.lines.length > 0 && linesForRender.length === 0 && axisIdCurrent != null) {
    guardStatus = "FROZEN";
  }

  const scaledLines = linesForRender.map((line) => ({
    ...line,
    y_screen: overlayLineYCss(line, geom, renderScale, allowCanonicalProjection),
    chart_left: overlayPhysXToCss(line.chart_left, geom, renderScale),
    chart_right: overlayPhysXToCss(line.chart_right, geom, renderScale),
  }));

  const volumeProfileOverlay = computeVolumeProfileOverlayModel({
    showVolumeProfileOverlay: snapshot.showVolumeProfileOverlay && axisStableForIndicators,
    volumeProfile,
    effectiveChartRect,
    effectiveYMin,
    effectiveYMax,
    usingOcrChart,
    overlayRightMarginPx: snapshot.overlayRightMarginPx,
    renderScale,
    overlayEnabled: snapshot.effectiveVpDisplay?.overlay_enabled,
    effectiveVpStretchLines: snapshot.effectiveVpDisplay?.stretch_lines,
    maxVisibleHistogramLevels: snapshot.effectiveVpDisplay?.max_visible_histogram_levels,
    axisFit: data.axis_fit ?? null,
    geometry: geom,
    allowCanonicalProjection,
  });

  const linesForLayout = volumeProfileOverlay
    ? filterOverlayLinesForVpMode(scaledLines)
    : filterOverlayLinesWithoutVp(scaledLines);
  const positionedLines = axisStableForIndicators
    ? layoutOverlayLines(linesForLayout, H)
    : [];

  const histogramVisible =
    axisStableForIndicators &&
    snapshot.effectiveVpDisplay?.histogram_visible !== false &&
    snapshot.showVolumeProfileOverlay;
  const showLegacyOverlayIndicators = axisStableForIndicators && !volumeProfileOverlay;
  const showMetricOverlayLines =
    axisStableForIndicators &&
    volumeProfileOverlay != null &&
    snapshot.effectiveVpDisplay?.top_avg_visible !== false &&
    positionedLines.length > 0;
  const tapeBadges = computeTapeBadges({
    showTapeIntelligenceOverlay: snapshot.showTapeIntelligenceOverlay && axisStableForIndicators,
    tapeIntelligence,
    effectiveChartRect,
    effectiveVolumeProfileOverlay: volumeProfileOverlay,
    effectiveVpDisplay: snapshot.effectiveVpDisplay,
    showVolumeProfileOverlay: snapshot.showVolumeProfileOverlay,
    usingOcrChart,
    renderScale,
    effectiveYMin,
    effectiveYMax,
    axisFit: data.axis_fit ?? null,
    geometry: geom,
    allowCanonicalProjection,
  });

  const effectiveFallbackReason = scaledChartRect
    ? ""
    : snapshot.axisUnusableReason || "axis_unavailable";

  if (!axisStableForIndicators && guardStatus === "OK") {
    guardStatus = "FROZEN";
  }

  const frame: OverlayRenderFrame = {
    viewportWidth: W,
    viewportHeight: H,
    renderScale,
    scaledChartRect,
    effectiveChartRect,
    effectiveYMin,
    effectiveYMax,
    positionedLines,
    volumeProfileOverlay,
    tapeBadges,
    histogramVisible,
    showLegacyOverlayIndicators,
    showMetricOverlayLines,
    showVolumeProfileOverlay: snapshot.showVolumeProfileOverlay,
    showTapeIntelligenceOverlay: snapshot.showTapeIntelligenceOverlay,
    usingOcrChart,
    effectiveFallbackReason,
    vpFallbackMode: snapshot.vpFallbackMode,
    guardStatus,
  };

  return {
    frame,
    renderItemsCount: countRenderItems(frame),
    error: null,
    viewportInvalid: false,
  };
}

export function safeBuildOverlayFrame(
  snapshot: OverlayLayoutSnapshot,
  diag?: OverlayDiagFlags | null,
): BuildOverlayFrameResult {
  try {
    return buildOverlayFrame(snapshot, diag);
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e));
    return { frame: null, renderItemsCount: 0, error: err, viewportInvalid: false };
  }
}
