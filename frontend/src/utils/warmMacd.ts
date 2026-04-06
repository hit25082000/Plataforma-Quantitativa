import { distributorApiBase } from "../config/distributorApi";
import { useMarketStore } from "../store/marketStore";
import type { MacdSignalMessage } from "../types/messages";

/**
 * Preenche MACD/IFR a partir de estado persistido + CSV no distributor (sem esperar trade).
 * Útil ao abrir o app ou após trocar de ativo (clearMarketData).
 */
export async function fetchWarmMacdSnapshot(): Promise<void> {
  const store = useMarketStore.getState();
  const symbol = store.selectedTicker.split(" · ")[0]?.trim() || "WINFUT";
  const base = distributorApiBase();
  const path = `/api/warm-macd?ticker=${encodeURIComponent(symbol)}`;
  const url = base ? `${base}${path}` : path;
  try {
    const res = await fetch(url);
    if (!res.ok) return;
    const m = (await res.json()) as MacdSignalMessage;
    if (m.topic === "market" && m.type === "macd_signal") {
      store.updateMacd(m);
    }
  } catch {
    // distributor indisponível ou sem histórico suficiente
  }
}
