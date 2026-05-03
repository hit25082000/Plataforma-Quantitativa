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

export interface OverlayLine {
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
