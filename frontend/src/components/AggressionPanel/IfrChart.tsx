import {
  LineChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  YAxis,
} from "recharts";
import { useMarketStore } from "../../store/marketStore";

const IFR_ABOVE = [70, 75, 80, 85, 90, 95] as const;
const IFR_BELOW = [30, 20, 15, 10] as const;

export function IfrChart() {
  const macdHistory = useMarketStore((s) => s.macdHistory);
  const data = macdHistory
    .filter((m): m is typeof m & { rsi: number } => m.rsi != null)
    .map((m, i) => ({ i, rsi: m.rsi }));

  return (
    <div className="h-24 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <YAxis domain={[0, 100]} hide width={0} />
          {IFR_ABOVE.map((y) => (
            <ReferenceLine
              key={y}
              y={y}
              stroke="rgba(34, 197, 94, 0.5)"
              strokeWidth={1}
              strokeDasharray="2 2"
            />
          ))}
          {IFR_BELOW.map((y) => (
            <ReferenceLine
              key={y}
              y={y}
              stroke="rgba(239, 68, 68, 0.5)"
              strokeWidth={1}
              strokeDasharray="2 2"
            />
          ))}
          <Line
            type="monotone"
            dataKey="rsi"
            stroke="#94a3b8"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
