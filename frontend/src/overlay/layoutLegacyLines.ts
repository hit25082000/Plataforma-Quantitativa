import { LABEL_H, LABEL_MARGIN_PX, LABEL_MIN_GAP } from "./overlayConstants";
import type { OverlayLine, PositionedOverlayLine } from "./overlayFrameTypes";
import { clamp } from "./chartGeom";

export function layoutOverlayLines(lines: OverlayLine[], screenH: number): PositionedOverlayLine[] {
  if (lines.length === 0) return [];

  const sortedByY = lines
    .map((line, index) => ({ line, index }))
    .sort((a, b) => a.line.y_screen - b.line.y_screen);

  const gaps: number[] = [];
  for (let i = 1; i < sortedByY.length; i++) {
    gaps.push(Math.abs(sortedByY[i].line.y_screen - sortedByY[i - 1].line.y_screen));
  }
  const avgGap = gaps.length > 0 ? gaps.reduce((acc, g) => acc + g, 0) / gaps.length : LABEL_MIN_GAP;
  const dense = sortedByY.length >= 4 || avgGap < LABEL_MIN_GAP + 8;

  const minCenter = LABEL_H / 2 + LABEL_MARGIN_PX;
  const maxCenter = screenH - LABEL_H / 2 - LABEL_MARGIN_PX;
  const centers = sortedByY.map((x) => clamp(x.line.y_screen, minCenter, maxCenter));

  for (let i = 1; i < centers.length; i++) {
    centers[i] = Math.max(centers[i], centers[i - 1] + LABEL_MIN_GAP);
  }

  const overflowBottom = centers[centers.length - 1] - maxCenter;
  if (overflowBottom > 0) {
    for (let i = 0; i < centers.length; i++) centers[i] -= overflowBottom;
  }

  for (let i = centers.length - 2; i >= 0; i--) {
    centers[i] = Math.min(centers[i], centers[i + 1] - LABEL_MIN_GAP);
  }

  const overflowTop = minCenter - centers[0];
  if (overflowTop > 0) {
    for (let i = 0; i < centers.length; i++) centers[i] += overflowTop;
  }

  const arranged = sortedByY.map((x, i) => ({
    line: x.line,
    index: x.index,
    labelY: clamp(centers[i], minCenter, maxCenter),
    rank: i + 1,
    dense,
  }));

  const byOriginal = new Array<PositionedOverlayLine>(arranged.length);
  for (const item of arranged) {
    byOriginal[item.index] = {
      ...item.line,
      labelY: item.labelY,
      rank: item.rank,
      dense: item.dense,
    };
  }
  return byOriginal;
}
