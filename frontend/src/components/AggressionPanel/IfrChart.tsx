import type { MacdSignalMessage } from "../../types/messages";
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

function usableRsi(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Lê RSI do candle (evita null/NaN vindos do JSON ou mensagens incompletas). */
function rsiFromMacdMsg(
  m: MacdSignalMessage,
  field: "rsi9" | "rsi18" | "rsi30",
): number | null {
  const direct: unknown = m[field];
  if (usableRsi(direct)) return direct;
  if (field === "rsi9" && usableRsi(m.rsi)) return m.rsi;
  if (typeof direct === "string") {
    const n = Number(direct.replace(",", "."));
    if (usableRsi(n)) return n;
  }
  return null;
}

export function IfrChart({ variant, fillHeight }: IfrChartProps) {
  const config = getVariantConfig(variant);
  const { rsiField } = config;
  const macdHistory = useMarketStore((s) => s.macdHistory);

  const data = macdHistory
    .map((m, i) => ({ i, rsi: rsiFromMacdMsg(m, rsiField) }))
    .filter((m): m is { i: number; rsi: number } => m.rsi != null);
  const showingEmpty = data.length === 0;
  const currentRsi = data.length > 0 ? data[data.length - 1].rsi : null;

  const heightClass = fillHeight ? "h-full min-h-[4.5rem]" : "h-16";

  return (
    <div
      className={`${heightClass} w-full flex items-center justify-center rounded border border-border/50 bg-bg/50`}
      aria-label={`IFR ${variant} (valor atual)`}
    >
      <span className="font-mono text-xs font-semibold text-text/90 tabular-nums">
        {showingEmpty || currentRsi == null
          ? "—"
          : currentRsi.toLocaleString("pt-BR", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
      </span>
    </div>
  );
}
