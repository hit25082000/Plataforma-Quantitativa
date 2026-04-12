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