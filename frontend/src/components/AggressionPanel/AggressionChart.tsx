import {
  LineChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  YAxis,
} from "recharts";
import { AGGRESSION_STEP, useMarketStore } from "../../store/marketStore";
import { formatQty } from "../../utils/formatters";

export function AggressionChart() {
  const aggrHistory = useMarketStore((s) => s.aggrHistory);

  const data = aggrHistory.map((v, i) => ({
    i,
    v,
    pos: v >= 0 ? v : null,
    neg: v < 0 ? v : null,
  }));

  const tickFormatter = (value: number) =>
    formatQty(Math.round(value / AGGRESSION_STEP) * AGGRESSION_STEP);

  return (
    <div className="h-24 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <YAxis
            domain={["auto", "auto"]}
            hide
            tickFormatter={tickFormatter}
          />
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
