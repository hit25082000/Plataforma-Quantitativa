import type { TapeIntelligenceMessage } from "../types/messages";
import type { VpOverlayDisplay } from "../types/messages";
import type { ScaledChartRect, TapeBadgeModel, VolumeProfileOverlayModel } from "./overlayFrameTypes";
import { clamp, scaledPriceY } from "./chartGeom";

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
  const baseX = Math.max(chartForTape.left + 12, effectiveVolumeProfileOverlay.profileLeft - 124);
  const initialBadges: TapeBadgeModel[] = [
    {
      key: "poc",
      label: "POC",
      player: tapeIntelligence.poc_player,
      playerName: tapeIntelligence.poc_player_name,
      side: "",
      y:
        scaledPriceY(
          preferExplicitY ? tapeIntelligence.poc_y : undefined,
          tapeIntelligence.poc_price,
          chartForTape,
          renderScale,
          effectiveYMin,
          effectiveYMax,
        ) ?? effectiveVolumeProfileOverlay.pocY ?? chartForTape.top,
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
      y:
        scaledPriceY(
          preferExplicitY ? tapeIntelligence.val_y : undefined,
          tapeIntelligence.val_price,
          chartForTape,
          renderScale,
          effectiveYMin,
          effectiveYMax,
        ) ?? effectiveVolumeProfileOverlay.valY ?? chartForTape.bottom,
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
      y:
        scaledPriceY(
          preferExplicitY ? tapeIntelligence.vah_y : undefined,
          tapeIntelligence.vah_price,
          chartForTape,
          renderScale,
          effectiveYMin,
          effectiveYMax,
        ) ?? effectiveVolumeProfileOverlay.vahY ?? chartForTape.top,
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
