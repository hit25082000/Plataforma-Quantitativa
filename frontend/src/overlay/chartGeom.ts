import type { VolumeProfileLevel } from "../types/messages";
import type { VolumeProfileMessage } from "../types/messages";
import type { ChartRect, ScaledChartRect } from "./overlayFrameTypes";
import {
  OVERLAY_LINE_LEFT_SHIFT_PX,
  VP_PROFILE_MAX_WIDTH_PX,
  VP_PROFILE_MIN_WIDTH_PX,
  VP_PROFILE_RIGHT_GAP_PX,
  VP_PROFILE_WIDTH_RATIO,
  VP_MAX_RENDER_LEVELS,
} from "./overlayConstants";

export function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

export function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function scaleChartRect(rect: ChartRect | null | undefined, scale: number): ScaledChartRect | null {
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

export function scaledPriceY(
  explicitY: number | undefined,
  price: number,
  chart: ScaledChartRect,
  renderScale: number,
  yMin: number | null,
  yMax: number | null,
): number | null {
  if (isFiniteNumber(explicitY)) return explicitY * renderScale;
  return priceToChartY(price, chart, yMin, yMax);
}

export function levelTotalVol(level: VolumeProfileLevel): number {
  const total = Number(level.total_vol);
  if (Number.isFinite(total) && total > 0) return total;
  const bid = Number(level.bid_vol);
  const ask = Number(level.ask_vol);
  return Math.max(0, (Number.isFinite(bid) ? bid : 0) + (Number.isFinite(ask) ? ask : 0));
}

export function medianPositive(values: number[]): number | null {
  const positives = values.filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (positives.length === 0) return null;
  const mid = Math.floor(positives.length / 2);
  return positives.length % 2 === 0
    ? (positives[mid - 1] + positives[mid]) / 2
    : positives[mid];
}

export function volumeProfilePriceRange(
  volumeProfile: VolumeProfileMessage | null,
): { min: number; max: number } | null {
  if (!volumeProfile || !Array.isArray(volumeProfile.levels)) return null;
  const prices = volumeProfile.levels
    .map((level) => Number(level.price))
    .filter((price) => Number.isFinite(price));
  if (prices.length === 0) return null;
  const anchor = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
  };
  const anchors = [anchor(volumeProfile.poc), anchor(volumeProfile.vah), anchor(volumeProfile.val)].filter(
    (n) => Number.isFinite(n),
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

export function fallbackChartRectForVp(width: number, height: number): ScaledChartRect | null {
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

export function computeEffectiveYRange(params: {
  scaledChartRect: ScaledChartRect | null;
  dataYMin: number | null;
  dataYMax: number | null;
  manualCalibrationOk: boolean;
  manualTop: number | null;
  manualBot: number | null;
  fallbackYLock: { min: number; max: number } | null;
  vpRange: { min: number; max: number } | null;
}): { effectiveYMin: number | null; effectiveYMax: number | null; usingOcrChart: boolean } {
  const {
    scaledChartRect,
    dataYMin,
    dataYMax,
    manualCalibrationOk,
    manualTop,
    manualBot,
    fallbackYLock,
    vpRange,
  } = params;
  if (scaledChartRect) {
    return {
      effectiveYMin: dataYMin,
      effectiveYMax: dataYMax,
      usingOcrChart: true,
    };
  }
  const manualMin =
    manualCalibrationOk && typeof manualTop === "number" && typeof manualBot === "number"
      ? Math.min(manualTop, manualBot)
      : null;
  const manualMax =
    manualCalibrationOk && typeof manualTop === "number" && typeof manualBot === "number"
      ? Math.max(manualTop, manualBot)
      : null;
  return {
    effectiveYMin: manualCalibrationOk ? manualMin : (fallbackYLock?.min ?? vpRange?.min ?? null),
    effectiveYMax: manualCalibrationOk ? manualMax : (fallbackYLock?.max ?? vpRange?.max ?? null),
    usingOcrChart: false,
  };
}

export function computeVolumeProfileOverlayModel(params: {
  showVolumeProfileOverlay: boolean;
  volumeProfile: VolumeProfileMessage | null;
  effectiveChartRect: ScaledChartRect | null;
  effectiveYMin: number | null;
  effectiveYMax: number | null;
  usingOcrChart: boolean;
  overlayRightMarginPx: number;
  renderScale: number;
  overlayEnabled?: boolean | null;
  effectiveVpStretchLines?: boolean | null;
  maxVisibleHistogramLevels?: number | null;
}): import("./overlayFrameTypes").VolumeProfileOverlayModel | null {
  const {
    showVolumeProfileOverlay,
    volumeProfile,
    effectiveChartRect,
    effectiveYMin: minForVp,
    effectiveYMax: maxForVp,
    usingOcrChart,
    overlayRightMarginPx,
    renderScale,
    overlayEnabled,
    effectiveVpStretchLines,
    maxVisibleHistogramLevels,
  } = params;
  if (!showVolumeProfileOverlay || !volumeProfile || !effectiveChartRect || overlayEnabled === false) {
    return null;
  }
  const chartForVp = effectiveChartRect;
  const preferExplicitY = usingOcrChart;
  const rawLevels = Array.isArray(volumeProfile.levels)
    ? volumeProfile.levels.slice(0, VP_MAX_RENDER_LEVELS)
    : [];
  const levelsWithExplicitY = rawLevels.filter((level) => isFiniteNumber(level.y)).length;
  const levelsWithY = rawLevels
    .map((level) => {
      const y = scaledPriceY(
        preferExplicitY ? level.y : undefined,
        Number(level.price),
        chartForVp,
        renderScale,
        minForVp,
        maxForVp,
      );
      const totalVol = levelTotalVol(level);
      if (y == null || totalVol <= 0 || !Number.isFinite(level.price)) return null;
      return { level, y, totalVol };
    })
    .filter((x): x is NonNullable<typeof x> => x != null)
    .filter(({ y }) => y >= chartForVp.top - 4 && y <= chartForVp.bottom + 4)
    .sort((a, b) => a.y - b.y);
  if (levelsWithY.length === 0) return null;

  const pricesFromLevels = levelsWithY
    .map((x) => Number(x.level.price))
    .filter((p) => Number.isFinite(p));
  const minPL = pricesFromLevels.length ? Math.min(...pricesFromLevels) : NaN;
  const maxPL = pricesFromLevels.length ? Math.max(...pricesFromLevels) : NaN;
  const pickFin = (raw: unknown, fallback: number) => {
    const n = Number(raw);
    return Number.isFinite(n) ? n : fallback;
  };
  const valRaw = pickFin(volumeProfile.val, minPL);
  const vahRaw = pickFin(volumeProfile.vah, maxPL);
  let valNum = Number.isFinite(valRaw) ? valRaw : minPL;
  let vahNum = Number.isFinite(vahRaw) ? vahRaw : maxPL;
  if (!Number.isFinite(valNum) && Number.isFinite(minPL)) valNum = minPL;
  if (!Number.isFinite(vahNum) && Number.isFinite(maxPL)) vahNum = maxPL;
  if (!Number.isFinite(valNum) || !Number.isFinite(vahNum)) {
    const c = Number.isFinite(minPL) ? minPL : 0;
    valNum = c;
    vahNum = c + 1;
  }
  const valBand = Math.min(valNum, vahNum);
  const vahBand = Math.max(valNum, vahNum);
  const pocNum = pickFin(
    volumeProfile.poc,
    Number.isFinite(minPL) && Number.isFinite(maxPL) ? (minPL + maxPL) / 2 : valBand,
  );

  const profileWidth = Math.min(
    Math.max(chartForVp.width * VP_PROFILE_WIDTH_RATIO, VP_PROFILE_MIN_WIDTH_PX),
    Math.min(VP_PROFILE_MAX_WIDTH_PX, Math.max(48, chartForVp.width - 16)),
  );
  const maxRight = chartForVp.right - VP_PROFILE_RIGHT_GAP_PX;
  const minRight = chartForVp.left + profileWidth + VP_PROFILE_RIGHT_GAP_PX;
  const targetRight = chartForVp.right - overlayRightMarginPx - OVERLAY_LINE_LEFT_SHIFT_PX;
  const profileRight = maxRight >= minRight ? clamp(targetRight, minRight, maxRight) : maxRight;
  const profileLeft = profileRight - profileWidth;
  const stretch = effectiveVpStretchLines === true;
  const lineEndX = stretch
    ? clamp(
        chartForVp.right - overlayRightMarginPx - OVERLAY_LINE_LEFT_SHIFT_PX,
        profileLeft + 32,
        chartForVp.right - 6,
      )
    : profileRight;
  const maxVol = Math.max(1, ...levelsWithY.map((x) => x.totalVol));
  const yGaps: number[] = [];
  for (let i = 1; i < levelsWithY.length; i++) {
    yGaps.push(Math.abs(levelsWithY[i].y - levelsWithY[i - 1].y));
  }
  const fallbackStepHeight =
    isFiniteNumber(volumeProfile.price_step) &&
    isFiniteNumber(minForVp) &&
    isFiniteNumber(maxForVp) &&
    minForVp !== maxForVp
      ? (Math.abs(volumeProfile.price_step) / Math.abs(maxForVp - minForVp)) * chartForVp.height
      : 5;
  const levelHeight = clamp((medianPositive(yGaps) ?? fallbackStepHeight) * 0.78, 1.25, 4.5);
  const renderLevels = levelsWithY.map(({ level, y, totalVol }) => {
    const ySafe = Number.isFinite(y) ? y : chartForVp.top + chartForVp.height / 2;
    const width = Math.max(2, (totalVol / maxVol) * profileWidth);
    const priceN = Number(level.price);
    return {
      price: Number.isFinite(priceN) ? priceN : pocNum,
      y: ySafe,
      width: Number.isFinite(width) ? width : 2,
      totalVol,
      bidVol: Math.max(0, Number(level.bid_vol) || 0),
      askVol: Math.max(0, Number(level.ask_vol) || 0),
      isPoc: Number.isFinite(priceN) && Number.isFinite(pocNum) && priceN === pocNum,
      inValueArea: Number.isFinite(priceN) && priceN >= valBand && priceN <= vahBand,
    };
  });
  const histogramCandidates = renderLevels.length;
  const rawMaxHist = maxVisibleHistogramLevels;
  const maxHist =
    typeof rawMaxHist === "number" && Number.isFinite(rawMaxHist)
      ? Math.min(VP_MAX_RENDER_LEVELS, Math.min(2000, Math.max(8, rawMaxHist)))
      : VP_MAX_RENDER_LEVELS;
  let cappedLevels =
    renderLevels.length <= maxHist
      ? renderLevels
      : [...renderLevels]
          .sort((a, b) => b.totalVol - a.totalVol)
          .slice(0, maxHist)
          .sort((a, b) => a.y - b.y);
  const denseThresholdPx = Math.max(3, levelHeight * 1.35);
  if (cappedLevels.length > 1) {
    const grouped: typeof cappedLevels = [];
    let current = { ...cappedLevels[0] };
    for (let i = 1; i < cappedLevels.length; i++) {
      const next = cappedLevels[i];
      const gap = Math.abs(next.y - current.y);
      if (gap <= denseThresholdPx) {
        const mergedVol = current.totalVol + next.totalVol;
        const mergedWeight = Math.max(1, mergedVol);
        current = {
          ...current,
          y: (current.y * current.totalVol + next.y * next.totalVol) / mergedWeight,
          totalVol: mergedVol,
          bidVol: current.bidVol + next.bidVol,
          askVol: current.askVol + next.askVol,
          isPoc: current.isPoc || next.isPoc,
          inValueArea: current.inValueArea || next.inValueArea,
          price: current.price,
        };
        continue;
      }
      grouped.push(current);
      current = { ...next };
    }
    grouped.push(current);
    cappedLevels = grouped;
  }
  const maxVolDraw = Math.max(1, ...cappedLevels.map((x) => x.totalVol));
  cappedLevels = cappedLevels.map((row) => ({
    ...row,
    width: Math.max(2, (row.totalVol / maxVolDraw) * profileWidth),
  }));
  const ySource = usingOcrChart ? "ocr" : "fallback";
  return {
    chart: chartForVp,
    profileLeft,
    profileRight,
    lineEndX,
    profileWidth,
    levelHeight,
    levels: cappedLevels,
    histogramCandidates,
    histogramRendered: cappedLevels.length,
    histogramCoalesced: Math.max(0, renderLevels.length - cappedLevels.length),
    pocY: scaledPriceY(
      preferExplicitY ? volumeProfile.poc_y : undefined,
      pocNum,
      chartForVp,
      renderScale,
      minForVp,
      maxForVp,
    ),
    vahY: scaledPriceY(
      preferExplicitY ? volumeProfile.vah_y : undefined,
      vahBand,
      chartForVp,
      renderScale,
      minForVp,
      maxForVp,
    ),
    valY: scaledPriceY(
      preferExplicitY ? volumeProfile.val_y : undefined,
      valBand,
      chartForVp,
      renderScale,
      minForVp,
      maxForVp,
    ),
    poc: pocNum,
    vah: vahBand,
    val: valBand,
    totalVol: Number.isFinite(volumeProfile.total_vol)
      ? volumeProfile.total_vol
      : levelsWithY.reduce((acc, x) => acc + x.totalVol, 0),
    period: volumeProfile.period ?? "day",
    ySource:
      ySource === "ocr" &&
      isFiniteNumber(volumeProfile.poc_y) &&
      isFiniteNumber(volumeProfile.vah_y) &&
      isFiniteNumber(volumeProfile.val_y) &&
      levelsWithExplicitY > 0
        ? "ocr"
        : "fallback",
  };
}
