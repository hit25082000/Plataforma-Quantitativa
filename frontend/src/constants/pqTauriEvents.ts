/** Emitido em todas as janelas após gravar config.json (`write_config`). */
export const PQ_CONFIG_SAVED_EVENT = "pq:config-saved";

/** profit-overlay-control → profit-overlay: expandir painel OCR debug HUD. */
export const PQ_OVERLAY_OCR_DEBUG_HUD_EVENT = "pq:overlay-ocr-debug-hud";

export type PqOverlayOcrDebugHudPayload = {
  expanded: boolean;
};

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
export const PQ_PROFIT_OVERLAY_OCR_STARTING_EVENT = "profit-overlay://ocr-starting";
export const PQ_PROFIT_OVERLAY_OCR_READY_EVENT = "profit-overlay://ocr-ready";
export const PQ_PROFIT_OVERLAY_OCR_ERROR_EVENT = "profit-overlay://ocr-error";

/** Janela principal (WS OCR) → WebView `profit-overlay` (WS direto no overlay pode ficar em CONNECTING no WebView2). */
export const PQ_PROFIT_OVERLAY_OCR_FRAME_EVENT = "pq:profit-overlay-ocr-frame";

export type PqProfitOverlayOcrFramePayload = {
  data: string;
  wsUrl: string;
};

/** Janela principal (WS engine) → WebView `profit-overlay` (VP overlay WS pode falhar no WebView2). */
export const PQ_PROFIT_OVERLAY_VP_RELAY_EVENT = "pq:profit-overlay-vp-relay";

export type PqProfitOverlayVpRelayPayload = {
  kind: "vp_overlay" | "volume_profile";
  data: string;
};

export type PqOcrOverlayAction = "recalibrate" | "freeze" | "manual" | "startup";
export type PqOcrOverlayStatus = "start" | "ok" | "error" | "released";

export type PqOcrOverlayStatusPayload = {
  action: PqOcrOverlayAction;
  status: PqOcrOverlayStatus;
  details?: Record<string, unknown>;
  ts_ms?: number;
};
