const WAITING_STATUSES = new Set([
  "connecting",
  "warming_up",
  "idle",
  "ocr_axis_warming",
  "reconnecting",
]);

export interface OcrAxisDeltaInterval {
  i: number;
  value_delta: number;
  y_delta: number;
  value_per_px_segment: number;
}

export interface OcrAxisDeltas {
  delta_first_last_value: number;
  delta_first_last_y: number;
  delta_intervals: OcrAxisDeltaInterval[];
  labels_count: number;
}

function extractInsufficientLabels(status: string): number | null {
  const m = /^ocr_insufficient_labels:(\d+)$/i.exec(status.trim());
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

export function overlayStatusColor(status: string): string {
  if (status === "ok" || status === "stable") return "#00FF88";
  if (status === "degraded" || status === "unstable") return "#FFB800";
  if (WAITING_STATUSES.has(status)) return "#FFB800";
  return "#FF4444";
}

export function overlayStatusText(
  status: string,
  yMin: number | null,
  yMax: number | null,
  axisDeltas?: OcrAxisDeltas | null,
): string {
  if (status === "ok") {
    const base = `OCR OK ${yMin?.toFixed(0)} - ${yMax?.toFixed(0)}`;
    if (!axisDeltas) return base;
    const d = axisDeltas.delta_first_last_value;
    const n = axisDeltas.delta_intervals?.length ?? 0;
    const sign = d > 0 ? "+" : "";
    return `${base} | Δ1-n ${sign}${d.toFixed(2)} | seg ${n}`;
  }
  if (status === "window_not_found") {
    return "OCR: janela do Profit não encontrada (deixe visível; em 2 telas, use a principal).";
  }
  if (status === "ocr_axis_warming") {
    return "OCR: a ler o eixo de preços (aguarde; em PC lento ou na 1ª execução pode demorar até ~1 min)…";
  }
  const labelsRead = extractInsufficientLabels(status);
  if (labelsRead != null) {
    if (labelsRead === 0) {
      return "OCR: eixo ilegível (0 labels). Ajuste zoom/contraste/fontes; com 2 monitores, use a mesma escala de texto em ambos ou deixe o Profit no monitor principal.";
    }
    return `OCR: eixo ilegível (${labelsRead} labels). Ajuste zoom/contraste/fontes do gráfico.`;
  }
  if (status === "ocr_axis_fit_failed") {
    return "OCR: leitura inconsistente do eixo de preço. Ajuste zoom/escala e tente novamente.";
  }
  if (status.startsWith("open_failed:")) {
    return status.replace(/^open_failed:\s*/i, "Falha ao abrir overlay: ");
  }
  if (status === "ocr_unreachable_retrying") {
    return "OCR indisponível (reconectando automaticamente; mantenha o overlay aberto e aguarde 1-2 min).";
  }
  if (status === "degraded") {
    return "OCR degradado (dados parciais ou atrasados).";
  }
  if (status === "unstable") {
    return "OCR instável (variação de leitura em monitoramento).";
  }
  if (status === "reconnecting") {
    return "OCR: reconectando serviço…";
  }
  if (status.startsWith("error:")) {
    return status.replace(/^error:\s*/i, "Erro OCR: ");
  }
  if (WAITING_STATUSES.has(status)) {
    if (status === "connecting") {
      return "OCR: a ligar o serviço (aguarde)…";
    }
    if (status === "warming_up") {
      return "OCR: a ligar ou a reconectar (PC lento: pode demorar até ~2 min; não feche o overlay).";
    }
    return `OCR ${status}`;
  }
  return `OCR ${status}`;
}
