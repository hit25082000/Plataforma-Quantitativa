import type { ChartRect } from "./overlayFrameTypes";

export function isFiniteChartRect(chart: ChartRect | null): chart is ChartRect {
  if (!chart) return false;
  return (
    Number.isFinite(chart.left) &&
    Number.isFinite(chart.top) &&
    Number.isFinite(chart.width) &&
    Number.isFinite(chart.height) &&
    chart.width > 0 &&
    chart.height > 0
  );
}

/** Window sizing + DPR only (badge-only overlay may have no chart yet). */
export function isOverlayWindowRenderable(params: { width: number; height: number; devicePixelRatio: number }): boolean {
  const { width, height, devicePixelRatio } = params;
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return false;
  if (!Number.isFinite(devicePixelRatio) || devicePixelRatio <= 0) return false;
  return true;
}

/** Full chart + window check when a chart is required for geometry. */
export function isOverlayViewportRenderable(params: {
  width: number;
  height: number;
  chart: ChartRect | null;
  devicePixelRatio: number;
  svgMatchesClient?: boolean | null;
}): boolean {
  if (!isOverlayWindowRenderable(params)) return false;
  return isFiniteChartRect(params.chart);
}
