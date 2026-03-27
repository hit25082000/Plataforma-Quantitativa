import { useMarketStore } from "../../store/marketStore";

export type IfrChartVariant = "9" | "18" | "30";

interface IfrChartProps {
  variant: IfrChartVariant;
  /** Em janela de widget: ocupa toda a altura disponível */
  fillHeight?: boolean;
}

function getVariantConfig(variant: IfrChartVariant) {
  switch (variant) {
    case "9":
      return { rsiField: "rsi9" as const };
    case "18":
      return { rsiField: "rsi18" as const };
    case "30":
      return { rsiField: "rsi30" as const };
  }
}

export function IfrChart({ variant, fillHeight }: IfrChartProps) {
  const config = getVariantConfig(variant);
  const { rsiField } = config;
  const macdHistory = useMarketStore((s) => s.macdHistory);

  const data = macdHistory
    .map((m, i) => ({ i, rsi: m[rsiField] }))
    .filter((m): m is { i: number; rsi: number } => typeof m.rsi === "number");
  const showingEmpty = data.length === 0;
  const currentRsi = data.length > 0 ? data[data.length - 1].rsi : null;

  const heightClass = fillHeight ? "h-full min-h-[4.5rem]" : "h-16";

  return (
    <div
      className={`${heightClass} w-full flex items-center justify-center rounded border border-border/50 bg-bg/50`}
      aria-label={`IFR ${variant} (valor atual)`}
    >
      <span className="font-mono text-xs font-semibold text-text/90 tabular-nums">
        {showingEmpty || currentRsi == null ? "—" : currentRsi.toFixed(2)}
      </span>
    </div>
  );
}
