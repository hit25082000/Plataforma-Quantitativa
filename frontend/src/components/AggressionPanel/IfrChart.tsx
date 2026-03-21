import { useMarketStore } from "../../store/marketStore";

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
  /** Em janela de widget: ocupa toda a altura disponível */
  fillHeight?: boolean;
}

function getVariantConfig(variant: IfrChartVariant) {
  switch (variant) {
    case "9":
      return { period: 9, source: "macd-or-prices" as const };
    case "30min":
      return { period: 9, source: "macd-only" as const };
    case "18":
      return { period: 18, source: "prices-only" as const };
  }
}

export function IfrChart({ variant, fillHeight }: IfrChartProps) {
  const config = getVariantConfig(variant);
  const { period, source } = config;
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
  const currentRsi = data.length > 0 ? data[data.length - 1].rsi : null;

  const heightClass = fillHeight ? "h-full min-h-[4.5rem]" : "h-16";

  return (
    <div
      className={`${heightClass} w-full flex items-center justify-center rounded border border-border/50 bg-bg/50`}
      aria-label={`IFR ${variant} (valor atual)`}
    >
      <span className="font-mono text-xs font-semibold text-text/90 tabular-nums">
        {showingEmpty || currentRsi == null ? "—" : Math.round(currentRsi)}
      </span>
    </div>
  );
}
