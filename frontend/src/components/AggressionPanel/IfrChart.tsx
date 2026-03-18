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

function calcRsiWilder(closes: number[], period: number): number {
  if (closes.length < period + 1) return 50;
  const last = closes.slice(-(period + 1));
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const change = last[i] - last[i - 1];
    if (change > 0) avgGain += change;
    else avgLoss += -change;
  }
  avgGain /= period;
  avgLoss /= period;
  if (avgLoss < 1e-10) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

export type IfrChartVariant = "9" | "30min" | "18";

interface IfrChartProps {
  variant: IfrChartVariant;
}

function getVariantConfig(variant: IfrChartVariant) {
  switch (variant) {
    case "9":
      return { period: 9, source: "macd-or-prices" as const, emptyLabel: "Aguardando dados IFR 9..." };
    case "30min":
      return { period: 9, source: "macd-only" as const, emptyLabel: "Aguardando dados (candles 30min)..." };
    case "18":
      return { period: 18, source: "prices-only" as const, emptyLabel: "Aguardando dados IFR 18..." };
  }
}

export function IfrChart({ variant }: IfrChartProps) {
  const config = getVariantConfig(variant);
  const { period, source, emptyLabel } = config;
  const macdHistory = useMarketStore((s) => s.macdHistory);
  const priceCloses = useMarketStore((s) => s.priceCloses);

  const dataFromMacd =
    source !== "prices-only"
      ? macdHistory
          .filter((m): m is typeof m & { rsi: number } => m.rsi != null)
          .map((m, i) => ({ i, rsi: m.rsi }))
      : [];

  const dataFromPrices: { i: number; rsi: number }[] = [];
  if ((source === "macd-or-prices" || source === "prices-only") && priceCloses.length >= period + 1) {
    for (let i = period; i < priceCloses.length; i++) {
      dataFromPrices.push({
        i: i - period,
        rsi: calcRsiWilder(priceCloses.slice(0, i + 1), period),
      });
    }
  }

  const data =
    source === "macd-only"
      ? dataFromMacd
      : source === "prices-only"
        ? dataFromPrices
        : dataFromMacd.length > 0
          ? dataFromMacd
          : dataFromPrices;
  const showingEmpty = data.length === 0;

  if (showingEmpty) {
    return (
      <div className="h-24 min-h-[6rem] w-full flex items-center justify-center rounded border border-border/50 bg-bg/50">
        <p className="text-text/70 text-xs">{emptyLabel}</p>
      </div>
    );
  }

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
