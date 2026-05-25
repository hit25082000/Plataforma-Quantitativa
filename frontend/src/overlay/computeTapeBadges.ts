import type { TapeIntelligenceMessage } from "../types/messages";
import type { VpOverlayDisplay } from "../types/messages";
import type {
  OverlayAxisFitCanonical,
  OverlayGeometryPayload,
  ScaledChartRect,
  TapeBadgeModel,
  VolumeProfileOverlayModel,
} from "./overlayFrameTypes";
import { clamp, isFiniteNumber, overlayPriceToSvgY, scaledPriceY } from "./chartGeom";

export function computeTapeBadges(params: {
  showTapeIntelligenceOverlay: boolean;
  tapeIntelligence: TapeIntelligenceMessage | null;
  effectiveChartRect: ScaledChartRect | null;
  effectiveVolumeProfileOverlay: VolumeProfileOverlayModel | null;
  effectiveVpDisplay: VpOverlayDisplay;
  showVolumeProfileOverlay: boolean;
  usingOcrChart: boolean;
  renderScale: number;
  effectiveYMin: number | null;
  effectiveYMax: number | null;
  axisFit?: OverlayAxisFitCanonical | null;
  geometry?: OverlayGeometryPayload | null;
  allowCanonicalProjection?: boolean;
}): TapeBadgeModel[] {
  const {
    showTapeIntelligenceOverlay,
    tapeIntelligence,
    effectiveChartRect,
    effectiveVolumeProfileOverlay,
    effectiveVpDisplay,
    showVolumeProfileOverlay,
    usingOcrChart,
    renderScale,
    effectiveYMin,
    effectiveYMax,
    axisFit,
    geometry,
    allowCanonicalProjection = false,
  } = params;
  if (
    !showTapeIntelligenceOverlay ||
    !tapeIntelligence ||
    !effectiveChartRect ||
    !effectiveVolumeProfileOverlay ||
    effectiveVpDisplay?.labels_visible === false
  ) {
    return [];
  }
  const chartForTape = effectiveChartRect;
  const preferExplicitY = usingOcrChart;
  const useCanon = Boolean(allowCanonicalProjection && axisFit && geometry);
  const tapeY = (
    explicitY: number | undefined,
    price: number,
    fallback: number,
    overlayAnchorY: number | null | undefined,
  ): number => {
    if (useCanon) {
      const cy = overlayPriceToSvgY(price, axisFit ?? null, geometry ?? null, renderScale, true);
      if (cy != null) return cy;
    }
    if (preferExplicitY && isFiniteNumber(explicitY)) {
      return (
        scaledPriceY(explicitY, price, chartForTape, renderScale, effectiveYMin, effectiveYMax, geometry) ??
        fallback
      );
    }
    if (isFiniteNumber(overlayAnchorY)) return overlayAnchorY;
    return (
      scaledPriceY(undefined, price, chartForTape, renderScale, effectiveYMin, effectiveYMax, geometry) ??
      fallback
    );
  };
  const baseX = Math.max(chartForTape.left + 12, effectiveVolumeProfileOverlay.profileLeft - 124);
  const initialBadges: TapeBadgeModel[] = [
    {
      key: "poc",
      label: "POC",
      player: tapeIntelligence.poc_player,
      playerName: tapeIntelligence.poc_player_name,
      side: "",
      y: tapeY(
        tapeIntelligence.poc_y,
        tapeIntelligence.poc_price,
        chartForTape.top,
        effectiveVolumeProfileOverlay.pocY,
      ),
      x: baseX,
      color: "#FDBA74",
      top3: tapeIntelligence.poc_top3 ?? [],
    },
    {
      key: "val",
      label: "FUNDO",
      player: tapeIntelligence.val_buyer,
      playerName: tapeIntelligence.val_buyer_name,
      side: "B",
      y: tapeY(
        tapeIntelligence.val_y,
        tapeIntelligence.val_price,
        chartForTape.bottom,
        effectiveVolumeProfileOverlay.valY,
      ),
      x: baseX,
      color: "#e53935",
      top3: tapeIntelligence.val_top3 ?? [],
    },
    {
      key: "vah",
      label: "TOPO",
      player: tapeIntelligence.vah_seller,
      playerName: tapeIntelligence.vah_seller_name,
      side: "S",
      y: tapeY(
        tapeIntelligence.vah_y,
        tapeIntelligence.vah_price,
        chartForTape.top,
        effectiveVolumeProfileOverlay.vahY,
      ),
      x: baseX,
      color: "#e53935",
      top3: tapeIntelligence.vah_top3 ?? [],
    },
  ];
  const pocVis = effectiveVpDisplay?.poc_visible !== false;
  const vvVis = effectiveVpDisplay?.val_vah_visible !== false;
  const vpAnchorsVisible = showVolumeProfileOverlay && !!effectiveVolumeProfileOverlay;
  const suppressPocBadge = vpAnchorsVisible && pocVis;
  const suppressValVahBadges = vpAnchorsVisible && vvVis;
  const raw = initialBadges
    .filter((b) => (b.key === "poc" ? !suppressPocBadge : true))
    .filter((b) => (b.key === "val" || b.key === "vah" ? !suppressValVahBadges : true))
    .filter((b) => (b.key === "poc" ? pocVis : true))
    .filter((b) => (b.key === "val" || b.key === "vah" ? vvVis : true))
    .filter((badge) => Number.isFinite(badge.y))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < raw.length; i++) {
    if (raw[i].y - raw[i - 1].y < 22) raw[i].y = raw[i - 1].y + 22;
  }
  for (let i = raw.length - 2; i >= 0; i--) {
    if (raw[i + 1].y - raw[i].y < 22) raw[i].y = raw[i + 1].y - 22;
  }
  return raw.map((badge) => ({
    ...badge,
    y: clamp(badge.y, chartForTape.top + 12, chartForTape.bottom - 12),
  }));
}
