import type { OverlayCompatLine } from "./overlayUpdateCompat";

export const OVERLAY_MIN_VISUAL_DELTA_PX = 1;

function lineKey(line: OverlayCompatLine): string {
  return `${line.label ?? ""}:${line.value}`;
}

export function hasMeaningfulLineDiff(
  prevLines: OverlayCompatLine[],
  nextLines: OverlayCompatLine[],
  minVisualDeltaPx = OVERLAY_MIN_VISUAL_DELTA_PX,
): boolean {
  if (prevLines.length !== nextLines.length) return true;
  if (prevLines.length === 0) return false;

  const prevByKey = new Map(prevLines.map((line) => [lineKey(line), line]));
  for (const line of nextLines) {
    const prev = prevByKey.get(lineKey(line));
    if (!prev) return true;
    if (
      prev.color !== line.color ||
      prev.chart_left !== line.chart_left ||
      prev.chart_right !== line.chart_right ||
      prev.status !== line.status ||
      prev.out_of_bounds !== line.out_of_bounds
    ) {
      return true;
    }
    if (Math.abs(prev.y_screen - line.y_screen) >= minVisualDeltaPx) {
      return true;
    }
  }
  return false;
}
