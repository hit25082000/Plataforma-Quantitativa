import { OVERLAY_METRIC_LABELS } from "../hooks/useProfitOverlay";
import type { OverlayLine } from "./overlayFrameTypes";

const VP_OCR_LABEL_PREFIXES = ["VP POC", "VP VAH", "VP VAL"] as const;

const METRIC_LABEL_PREFIXES = [
  OVERLAY_METRIC_LABELS.ubs,
  OVERLAY_METRIC_LABELS.best_bid,
  OVERLAY_METRIC_LABELS.best_ask,
] as const;

export function isVpOcrOverlayLine(label?: string): boolean {
  const l = (label ?? "").trim();
  return VP_OCR_LABEL_PREFIXES.some((p) => l.startsWith(p));
}

export function isMetricOcrOverlayLine(label?: string): boolean {
  const l = (label ?? "").trim();
  if (!l) return false;
  if (l === OVERLAY_METRIC_LABELS.ubs) return true;
  return METRIC_LABEL_PREFIXES.some(
    (p) => p !== OVERLAY_METRIC_LABELS.ubs && l.startsWith(p),
  );
}

/** Com VP Sato nativo: só linhas de métricas do Overlay Control; exclui eco VP POC/VAL/VAH do OCR. */
export function filterOverlayLinesForVpMode(lines: OverlayLine[]): OverlayLine[] {
  return lines.filter((ln) => isMetricOcrOverlayLine(ln.label) && !isVpOcrOverlayLine(ln.label));
}

/** Sem VP nativo: todas as linhas OCR exceto alvos VP legados no OCR. */
export function filterOverlayLinesWithoutVp(lines: OverlayLine[]): OverlayLine[] {
  return lines.filter((ln) => !isVpOcrOverlayLine(ln.label));
}
