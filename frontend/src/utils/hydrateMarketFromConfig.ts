import { invoke } from "@tauri-apps/api/core";
import { useMarketStore, type IfrSeriesMode } from "../store/marketStore";

export type MarketConfigSlice = {
  selected_ticker?: string | null;
  selected_exchange?: string | null;
  renko_brick_points?: number | null;
  ifr_series?: string | null;
};

/** Aplica ticker + série IFR do config ao store (mesma regra que useTauriStartup). */
export function applyMarketConfigToStore(cfg: MarketConfigSlice): IfrSeriesMode {
  const ticker = (cfg.selected_ticker ?? "WINFUT").trim();
  const exchange = (cfg.selected_exchange ?? "BMF").trim();
  if (ticker && exchange) {
    useMarketStore.getState().setSelectedTicker(`${ticker} · ${exchange}`);
  }

  const ifrKey = (cfg.ifr_series ?? "").trim().toLowerCase();
  let ifrMode: IfrSeriesMode = "42r";
  if (ifrKey === "30m" || ifrKey === "30min") ifrMode = "30m";
  else if (ifrKey === "16r") ifrMode = "16r";
  else if (ifrKey === "42r") ifrMode = "42r";
  else if (cfg.renko_brick_points === 16) ifrMode = "16r";

  useMarketStore.getState().setIfrSeries(ifrMode);
  return ifrMode;
}

export async function readConfigAndHydrateMarketStore(): Promise<IfrSeriesMode> {
  const cfg = await invoke<MarketConfigSlice>("read_config");
  return applyMarketConfigToStore(cfg);
}
