import { emit } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { distributorApiBase } from "../../config/distributorApi";
import {
  PQ_IFR_SERIES_EVENT,
  type PqIfrSeriesPayload,
} from "../../constants/pqTauriEvents";
import { useMarketStore, type IfrSeriesMode } from "../../store/marketStore";
import { isTauri } from "../../utils/tauri";
import { fetchWarmMacdSnapshot } from "../../utils/warmMacd";

const OPTIONS: { mode: IfrSeriesMode; label: string }[] = [
  { mode: "42r", label: "42R" },
  { mode: "16r", label: "16R" },
  { mode: "30m", label: "30 min" },
];

async function pushIfrSeriesToDistributor(mode: IfrSeriesMode): Promise<boolean> {
  const base = distributorApiBase();
  const url = `${base}/api/set-renko-brick`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ series: mode }),
    });
    const data = (await res.json().catch(() => ({}))) as {
      success?: boolean;
    };
    return res.ok && data.success !== false;
  } catch {
    return false;
  }
}

export function RenkoBrickSelector() {
  const ifrSeries = useMarketStore((s) => s.ifrSeries);
  const ifrLoading = useMarketStore((s) => s.ifrLoading);
  const ifrLoadingSeries = useMarketStore((s) => s.ifrLoadingSeries);
  const setIfrSeries = useMarketStore((s) => s.setIfrSeries);
  const setIfrLoading = useMarketStore((s) => s.setIfrLoading);

  const apply = async (mode: IfrSeriesMode) => {
    setIfrSeries(mode);
    setIfrLoading(true, mode, "Atualizando IFR");
    if (isTauri()) {
      try {
        await invoke<{ success: boolean; message: string }>("set_ifr_series", {
          series: mode,
        });
        try {
          await emit<PqIfrSeriesPayload>(PQ_IFR_SERIES_EVENT, { series: mode });
        } catch {
          // sem listeners
        }
      } catch (e) {
        console.warn("IFR série: falha ao persistir/sincronizar", e);
      }
    } else {
      const ok = await pushIfrSeriesToDistributor(mode);
      if (!ok) console.warn("IFR série: distributor não aplicou (servidor em 8000?)");
    }
    void fetchWarmMacdSnapshot({
      retries: 8,
      retryDelayMs: 250,
      expectedSeries: mode,
    });
  };

  return (
    <div
      className="flex items-center rounded-md border border-border/50 bg-bg/60 overflow-hidden"
      role="group"
      aria-label="Série do IFR (Renko ou 30 minutos)"
    >
      {OPTIONS.map(({ mode, label }) => {
        const active = ifrSeries === mode;
        const loading = ifrLoading && ifrLoadingSeries === mode;
        return (
          <button
            key={mode}
            type="button"
            onClick={() => void apply(mode)}
            className={`min-w-[2.75rem] px-2 py-1 text-xs font-semibold font-mono transition-colors inline-flex items-center justify-center gap-1
              ${active ? "bg-emerald-500/20 text-emerald-300" : "text-text/60 hover:text-text/90 hover:bg-border/40"}`}
          >
            <span
              className={`h-2.5 w-2.5 rounded-full border-2 ${
                loading
                  ? "border-emerald-400/30 border-t-emerald-300 animate-spin"
                  : "border-transparent"
              }`}
              aria-hidden="true"
            />
            {label}
          </button>
        );
      })}
    </div>
  );
}
