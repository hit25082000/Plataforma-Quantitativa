import { distributorApiBase } from "../config/distributorApi";
import {
  normalizeIfrSeriesMode,
  useMarketStore,
  type IfrSeriesMode,
} from "../store/marketStore";
import type { MacdSignalMessage } from "../types/messages";

interface WarmMacdOptions {
  retries?: number;
  retryDelayMs?: number;
  ticker?: string;
  expectedSeries?: string;
  showLoading?: boolean;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let warmMacdLoadingSeq = 0;

function selectedSymbol(): string {
  return useMarketStore.getState().selectedTicker.split(" · ")[0]?.trim() || "WINFUT";
}

/**
 * Preenche MACD/IFR a partir de estado persistido + CSV no distributor (sem esperar trade).
 * Útil ao abrir o app ou após trocar de ativo (clearMarketData).
 */
export async function fetchWarmMacdSnapshot(options?: WarmMacdOptions): Promise<void> {
  const retries = Math.max(0, Math.floor(options?.retries ?? 0));
  const retryDelayMs = Math.max(50, Math.floor(options?.retryDelayMs ?? 250));
  const explicitTicker = options?.ticker?.trim();
  const expectedSeries = (options?.expectedSeries ?? "").trim().toLowerCase();
  const base = distributorApiBase();
  const initialStore = useMarketStore.getState();
  const symbol = explicitTicker || selectedSymbol();
  const requestedSeries: IfrSeriesMode =
    normalizeIfrSeriesMode(expectedSeries) ?? initialStore.ifrSeries;
  const showLoading = options?.showLoading !== false;
  const loadingSeq = showLoading ? ++warmMacdLoadingSeq : 0;

  if (showLoading) {
    initialStore.setIfrLoading(true, requestedSeries, "Atualizando IFR");
  }

  try {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const store = useMarketStore.getState();
        const series = requestedSeries;
        if (!explicitTicker && selectedSymbol() !== symbol) return;
        const query = new URLSearchParams({
          ticker: symbol,
          series,
          _ts: `${Date.now()}`,
        });
        const path = `/api/warm-macd?${query.toString()}`;
        const url = base ? `${base}${path}` : path;

        const res = await fetch(url, {
          cache: "no-store",
          headers: {
            "Cache-Control": "no-cache",
            Pragma: "no-cache",
          },
        });
        if (!res.ok) {
          if (
            attempt < retries &&
            (res.status === 404 ||
              res.status === 429 ||
              (res.status >= 500 && res.status <= 599))
          ) {
            await sleep(retryDelayMs);
            continue;
          }
          return;
        }

        const m = (await res.json()) as MacdSignalMessage;
        if (m.topic !== "market" || m.type !== "macd_signal") return;

        const incomingSeries = normalizeIfrSeriesMode(m.ifr_series);
        if (
          incomingSeries != null &&
          incomingSeries !== series &&
          attempt < retries &&
          typeof m.ifr_series === "string"
        ) {
          await sleep(retryDelayMs);
          continue;
        }

        store.updateMacd(m);
        return;
      } catch {
        if (attempt >= retries) {
          return;
        }
        await sleep(retryDelayMs);
      }
    }
  } finally {
    if (showLoading && loadingSeq === warmMacdLoadingSeq) {
      const store = useMarketStore.getState();
      if (store.ifrLoadingSeries === requestedSeries) {
        store.setIfrLoading(false);
      }
    }
  }
}
