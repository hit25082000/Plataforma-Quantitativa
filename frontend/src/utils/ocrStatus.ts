const WAITING_STATUSES = new Set([
  "connecting",
  "warming_up",
  "idle",
  "ocr_axis_warming",
  "ocr_starting",
  "ocr_connecting",
  "ocr_warming",
  "axis_waiting",
  "geometry_calibrating",
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

/** Payload legado / parcial do WS; `overlayStatusText` só usa deltas completos. */
export type OcrAxisDeltasOrLegacy = OcrAxisDeltas | Record<string, unknown>;

function extractInsufficientLabels(status: string): number | null {
  const m = /^ocr_insufficient_labels:(\d+)$/i.exec(status.trim());
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

const OK_STATUSES = new Set(["ok", "axis_stable"]);

export function overlayStatusColor(status: string): string {
  if (OK_STATUSES.has(status)) return "#00FF88";
  if (WAITING_STATUSES.has(status)) return "#FFB800";
  if (status === "degraded") return "#FFB800";
  return "#FF4444";
}

function isFullOcrAxisDeltas(v: OcrAxisDeltasOrLegacy | null | undefined): v is OcrAxisDeltas {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  const d = v as OcrAxisDeltas;
  return (
    typeof d.delta_first_last_value === "number" &&
    Number.isFinite(d.delta_first_last_value) &&
    Array.isArray(d.delta_intervals) &&
    typeof d.labels_count === "number"
  );
}

export function overlayStatusText(
  status: string,
  yMin: number | null,
  yMax: number | null,
  axisDeltas?: OcrAxisDeltasOrLegacy | null,
): string {
  if (status === "ok") {
    const base = `OCR OK ${yMin?.toFixed(0)} - ${yMax?.toFixed(0)}`;
    if (!axisDeltas || !isFullOcrAxisDeltas(axisDeltas)) return base;
    const d = axisDeltas.delta_first_last_value;
    const n = axisDeltas.delta_intervals.length;
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
    return "OCR indisponível (tentando reconectar; em PC lento aguarde mais 1–2 min).";
  }
  if (status === "ocr_starting") {
    return "OCR: iniciando em background...";
  }
  if (status === "ocr_connecting") {
    return "OCR: conectando websocket...";
  }
  if (status === "ocr_warming") {
    return "OCR: aquecendo modelo/eixo...";
  }
  if (status === "axis_waiting") {
    return "OCR: aguardando eixo estável para renderizar linhas.";
  }
  if (status === "geometry_calibrating") {
    return "OCR: geometria alterada — recalibrando eixo (sem linhas até estabilizar).";
  }
  if (status === "axis_stable") {
    return "OCR: eixo estável.";
  }
  if (status === "degraded") {
    return "OCR degradado: mantendo overlay sem linhas até estabilizar.";
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
