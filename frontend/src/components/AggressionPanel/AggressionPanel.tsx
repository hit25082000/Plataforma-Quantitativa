import { useMarketStore } from "../../store/marketStore";
import { formatPrice } from "../../utils/formatters";
import { OpenAsWidgetButton } from "../OpenAsWidgetButton";
import { BuyVsSellBar } from "./BuyVsSellBar";
import { AggressionChart } from "./AggressionChart";
import { IfrChart } from "./IfrChart";
import { TopBrokersTable } from "./TopBrokersTable";
import { UBSLine } from "./UBSLine";

const AGGRESSION_WIDGETS: { id: string; label: string }[] = [
  { id: "buy-vs-sell", label: "Buy vs Sell" },
  { id: "top-brokers", label: "Top Brokers" },
  { id: "aggression-chart", label: "Aggression Chart" },
  { id: "ifr-9", label: "IFR 9" },
  { id: "ifr-30min", label: "IFR 30min" },
  { id: "ifr-18", label: "IFR 18" },
  { id: "ubs-line", label: "UBS Line" },
  { id: "vwap", label: "VWAP" },
];

export function AggressionPanel() {
  const vwap = useMarketStore((s) => s.vwap);

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 text-sm font-semibold text-text/80 border-b border-border shrink-0 flex items-center justify-between gap-2">
        <span>AGGRESSION PANEL</span>
        <div className="relative flex items-center gap-1">
          {AGGRESSION_WIDGETS.map((w) => (
            <OpenAsWidgetButton
              key={w.id}
              widgetId={w.id}
              title={`Abrir ${w.label} em janela`}
              className="shrink-0 p-1 rounded hover:bg-border text-text/50 hover:text-text/80 text-xs"
            />
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <BuyVsSellBar />
        <TopBrokersTable />
        <div>
          <h3 className="text-xs font-semibold text-text/60 mb-2">Histórico</h3>
          <AggressionChart />
        </div>
        <div>
          <h3 className="text-xs font-semibold text-text/60 mb-2">IFR 9</h3>
          <IfrChart variant="9" />
        </div>
        <div>
          <h3 className="text-xs font-semibold text-text/60 mb-2">IFR 30min</h3>
          <IfrChart variant="30min" />
        </div>
        <div>
          <h3 className="text-xs font-semibold text-text/60 mb-2">IFR 18</h3>
          <IfrChart variant="18" />
        </div>
        <div>
          <UBSLine />
        </div>
        <div className="rounded border border-border/50 bg-bg/50 px-3 py-2">
          <p className="text-xs text-text/60 mb-0.5">Preço médio (Times & Trades — 1ª linha)</p>
          <p className="font-mono text-sm text-text/90">
            {vwap > 0 ? formatPrice(vwap) : "—"}
          </p>
        </div>
      </div>
    </div>
  );
}
