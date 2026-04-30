/** Emitido em todas as janelas após gravar config.json (`write_config`). */
export const PQ_CONFIG_SAVED_EVENT = "pq:config-saved";

/** Emitido na janela principal quando o ativo ativo muda (para hidratar widgets). */
export const PQ_SELECTED_ASSET_EVENT = "pq:selected-asset";

export type PqSelectedAssetPayload = {
  ticker: string;
  exchange: string;
};

/** Emitido ao mudar 42R / 16R / 30 min na barra (para widgets alinharem série IFR). */
export const PQ_IFR_SERIES_EVENT = "pq:ifr-series";

export type PqIfrSeriesPayload = {
  series: "42r" | "16r" | "30m";
};

/** Evento legado de recalibração (mantido por compatibilidade). */
export const PQ_OCR_RECALIBRATING_EVENT = "pq:ocr-recalibrating";

/** Evento canônico para status de OCR overlay (recalibrate/freeze/status). */
export const PQ_OCR_OVERLAY_STATUS_EVENT = "pq:ocr-overlay-status";

export type PqOcrOverlayAction = "recalibrate" | "freeze" | "manual";
export type PqOcrOverlayStatus = "start" | "ok" | "error" | "released";

export type PqOcrOverlayStatusPayload = {
  action: PqOcrOverlayAction;
  status: PqOcrOverlayStatus;
  details?: Record<string, unknown>;
  ts_ms?: number;
};