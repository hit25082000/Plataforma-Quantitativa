import { useMarketStore } from "../../store/marketStore";
import { formatPrice } from "../../utils/formatters";
import { BuyVsSellBar } from "./BuyVsSellBar";
import { AggressionChart } from "./AggressionChart";
import { IfrChart } from "./IfrChart";
import { TopBrokersTable } from "./TopBrokersTable";
import { UBSLine } from "./UBSLine";

export function AggressionPanel() {
  const vwap = useMarketStore((s) => s.vwap);

  return (
    <div className="h-full flex flex-col">
      <h2 className="px-4 py-2 text-sm font-semibold text-text/80 border-b border-border shrink-0">
        AGGRESSION PANEL
      </h2>
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
