import { useMarketStore } from "../../store/marketStore";

export function MacdChart() {
  const inSync = useMarketStore((s) => s.inSync);
  const macdHistory = useMarketStore((s) => s.macdHistory);
  const macdDirection = useMarketStore((s) => s.macdDirection);

  const maxAbs = Math.max(
    0.01,
    ...macdHistory.map((m) => Math.abs(m.histogram)),
  );

  const barColor = (direction: "buy" | "sell") => {
    if (!inSync) return "rgb(128, 128, 128)";
    return direction === "buy" ? "rgb(34, 197, 94)" : "rgb(239, 68, 68)";
  };

  return (
    <div className="h-full flex flex-col p-2">
      <h2 className="text-sm font-semibold text-text/80 border-b border-border pb-1 mb-2 shrink-0">
        MACD 30min {macdDirection != null && `(${macdDirection})`}
      </h2>
      <div className="flex-1 flex items-end gap-0.5 min-h-0">
        {macdHistory.length === 0 ? (
          <p className="text-text/40 text-xs self-center">Aguardando dados...</p>
        ) : (
          macdHistory.map((m, i) => {
            const h = m.histogram;
            const pct = Math.min(100, (Math.abs(h) / maxAbs) * 100);
            const color = barColor(m.direction);
            return (
              <div
                key={`${m.ts}-${i}`}
                className="flex-1 min-w-[4px] flex flex-col justify-end items-center"
                title={`${m.ts} hist=${h} ${m.direction}`}
              >
                <div
                  className="w-full rounded-t transition-all"
                  style={{
                    height: `${pct}%`,
                    minHeight: h !== 0 ? "4px" : "0",
                    backgroundColor: color,
                  }}
                />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
