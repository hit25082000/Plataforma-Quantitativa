import type { TapeIntelligenceLevel, TapeIntelligenceMessage, VolumeProfileMessage } from "../types/messages";
import type { VpOverlayDisplay } from "../types/messages";

/** Minimal chart rectangle (logical / CSS px). */
export interface ChartRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface ScaledChartRect extends ChartRect {
  right: number;
  bottom: number;
}

/** Retângulo em pixels físicos de ecrã (x,y,width,height). */
export interface OverlayScreenRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface OverlayGeometryPayload {
  chart_rect_screen_physical?: OverlayScreenRect | null;
  overlay_rect_screen_physical?: OverlayScreenRect | null;
  axis_rect_screen_physical?: OverlayScreenRect | null;
  dpi_scale?: number;
  capture_rect_screen?: OverlayScreenRect | null;
  chart_rect_screen?: { left: number; top: number; width: number; height: number } | null;
  overlay_rect_screen?: OverlayScreenRect | null;
  chart_rect_overlay?: unknown;
  scale_factor: number;
  monitor_id?: string | null;
  geometry_signature?: string;
}

export interface OverlayAxisFitCanonical {
  axis_id: number;
  model: string;
  coordinate_space?: string;
  price_ref?: number;
  slope: number;
  intercept: number;
  labels_count: number;
  avg_error_px?: number;
  max_error_px?: number;
  rmse?: number;
  r2?: number;
  created_at_ms?: number;
  geometry_signature?: string;
}

export interface OverlayAxisLabelSample {
  value: number;
  y_capture?: number;
  y_screen: number;
  y_chart?: number;
  y_predicted?: number;
  error_px?: number;
}

export interface OverlayLine {
  value: number;
  y_screen: number;
  y_capture?: number;
  y_screen_physical?: number;
  y_screen_logical?: number;
  y_overlay_css?: number;
  color: string;
  chart_left: number;
  chart_right: number;
  label?: string;
  status?: string;
  out_of_bounds?: boolean;
  line_id?: string;
  /** Pixel físico relativo ao topo do chart (eixo canónico). */
  y_chart?: number;
  frame_axis_id?: number;
  axis_source?: string;
}

export interface PositionedOverlayLine extends OverlayLine {
  labelY: number;
  rank: number;
  dense: boolean;
}

export interface VolumeProfileRenderableLevel {
  price: number;
  y: number;
  width: number;
  totalVol: number;
  bidVol: number;
  askVol: number;
  isPoc: boolean;
  inValueArea: boolean;
}

export interface VolumeProfileOverlayModel {
  chart: ScaledChartRect;
  profileLeft: number;
  profileRight: number;
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

export interface TapeBadgeModel {
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

export type OverlayGuardStatus = "OK" | "FROZEN" | "DEGRADED";

export interface OverlayDataSlice {
  lines: OverlayLine[];
  status: string;
  y_min: number | null;
  y_max: number | null;
  chart_rect?: ChartRect | null;
  geometry?: OverlayGeometryPayload | null;
  axis_fit?: OverlayAxisFitCanonical | null;
  axis_id?: number | null;
  axis_samples?: OverlayAxisLabelSample[] | null;
  axis_status?: string | null;
  normalized_axis_status?: string | null;
  last_good_axis_age_ms?: number | null;
  parsed_labels_count?: number | null;
}

export interface OverlayRenderFrame {
  viewportWidth: number;
  viewportHeight: number;
  renderScale: number;
  scaledChartRect: ScaledChartRect | null;
  effectiveChartRect: ScaledChartRect | null;
  effectiveYMin: number | null;
  effectiveYMax: number | null;
  /** Legacy horizontal lines (+ labels layout). */
  positionedLines: PositionedOverlayLine[];
  volumeProfileOverlay: VolumeProfileOverlayModel | null;
  tapeBadges: TapeBadgeModel[];
  histogramVisible: boolean;
  showLegacyOverlayIndicators: boolean;
  /** Linhas OCR de métricas (UBS / líderes) com VP Sato nativo ativo. */
  showMetricOverlayLines: boolean;
  showVolumeProfileOverlay: boolean;
  showTapeIntelligenceOverlay: boolean;
  usingOcrChart: boolean;
  effectiveFallbackReason: string;
  vpFallbackMode: string;
  guardStatus: OverlayGuardStatus;
}

export interface FallbackYLock {
  min: number;
  max: number;
}

/** Snapshot passed into buildOverlayFrame (throttled inputs). */
export interface OverlayLayoutSnapshot {
  viewportWidth: number;
  viewportHeight: number;
  devicePixelRatio: number;
  overlayRightMarginPx: number;
  showVolumeProfileOverlay: boolean;
  showTapeIntelligenceOverlay: boolean;
  vpFallbackMode: string;
  fallbackYLock: FallbackYLock | null;
  manualTop: number | null;
  manualBot: number | null;
  data: OverlayDataSlice;
  volumeProfile: VolumeProfileMessage | null;
  tapeIntelligence: TapeIntelligenceMessage | null;
  effectiveVpDisplay: VpOverlayDisplay;
  axisUsableForOcr: boolean;
  axisUnusableReason: string;
}

export interface BuildOverlayFrameResult {
  frame: OverlayRenderFrame | null;
  renderItemsCount: number;
  error: Error | null;
  viewportInvalid: boolean;
}
