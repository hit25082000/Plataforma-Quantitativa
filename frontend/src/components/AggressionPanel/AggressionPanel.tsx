import { BuyVsSellBar } from "./BuyVsSellBar";
import { AggressionChart } from "./AggressionChart";
import { TopBrokersTable } from "./TopBrokersTable";

export function AggressionPanel() {
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
      </div>
    </div>
  );
}
