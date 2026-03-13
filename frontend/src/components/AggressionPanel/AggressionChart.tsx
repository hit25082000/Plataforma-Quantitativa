import {
  LineChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  YAxis,
} from "recharts";
import { useMarketStore } from "../../store/marketStore";

export function AggressionChart() {
  const aggrHistory = useMarketStore((s) => s.aggrHistory);

  const data = aggrHistory.map((v, i) => ({
    i,
    v,
    pos: v >= 0 ? v : null,
    neg: v < 0 ? v : null,
  }));

  return (
    <div className="h-24 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <YAxis domain={["auto", "auto"]} hide />
          <ReferenceLine y={0} stroke="#4a4a4a" strokeWidth={1} />
          <Line
            type="monotone"
            dataKey="pos"
            stroke="#00ff88"
            strokeWidth={1.5}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="neg"
            stroke="#ff2244"
            strokeWidth={1.5}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
