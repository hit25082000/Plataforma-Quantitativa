import { useMarketStore } from "../../store/marketStore";

const TICKER_LABELS: Record<string, string> = {
  BOVA11: "BOVA11",
};

const ORDER = ["BOVA11"];

export function SyncPanel() {
  const inSync = useMarketStore((s) => s.inSync);
  const variations = useMarketStore((s) => s.syncVariations);

  return (
    <div className="flex flex-wrap items-center gap-2 p-2 border-b border-border bg-grid">
      <span className="text-xs font-semibold text-text/70 shrink-0">
        SYNC
      </span>
      {ORDER.map((ticker) => {
        const v = variations[ticker] ?? null;
        const label = TICKER_LABELS[ticker] ?? ticker;
        const inBand = v !== null && Math.abs(v) <= 0.1;
        return (
          <span
            key={ticker}
            className="text-xs px-2 py-1 rounded font-mono"
            title={`${ticker}: ${v !== null ? `${v}%` : "—"}`}
            style={{
              backgroundColor: inSync
                ? inBand
                  ? "rgba(34, 197, 94, 0.2)"
                  : "rgba(239, 68, 68, 0.2)"
                : "rgba(128, 128, 128, 0.3)",
              color: inSync
                ? inBand
                  ? "rgb(34, 197, 94)"
                  : "rgb(239, 68, 68)"
                : "rgb(160, 160, 160)",
            }}
          >
            {label} {v !== null ? `${v > 0 ? "+" : ""}${v}%` : "—"}
          </span>
        );
      })}
      <span
        className="text-xs font-medium ml-1"
        style={{
          color: inSync ? "rgb(34, 197, 94)" : "rgb(239, 68, 68)",
        }}
      >
        {inSync ? "IN SYNC" : "OUT OF SYNC"}
      </span>
    </div>
  );
}
