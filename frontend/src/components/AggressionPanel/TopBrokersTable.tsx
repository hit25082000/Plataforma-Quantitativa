import { useMarketStore } from "../../store/marketStore";
import { formatQty } from "../../utils/formatters";

function getTopN(
  totals: Record<number, number>,
  n: number
): { agentId: number; qty: number }[] {
  return Object.entries(totals)
    .map(([id, qty]) => ({ agentId: Number(id), qty }))
    .sort((a, b) => b.qty - a.qty)
    .slice(0, n);
}

export function TopBrokersTable() {
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);

  const topBuyers = getTopN(agentBuyTotals, 5);
  const topSellers = getTopN(agentSellTotals, 5);

  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h3 className="text-xs font-semibold text-text/60 mb-2">Top Compradores</h3>
        <div className="space-y-1 font-mono text-sm">
          {topBuyers.length === 0 ? (
            <p className="text-text/40">—</p>
          ) : (
            topBuyers.map(({ agentId, qty }) => (
              <div key={agentId} className="flex justify-between">
                <span className="text-text/80">#{agentId}</span>
                <span className="text-neon-buy">{formatQty(qty)} lotes</span>
              </div>
            ))
          )}
        </div>
      </div>
      <div>
        <h3 className="text-xs font-semibold text-text/60 mb-2">Top Vendedores</h3>
        <div className="space-y-1 font-mono text-sm">
          {topSellers.length === 0 ? (
            <p className="text-text/40">—</p>
          ) : (
            topSellers.map(({ agentId, qty }) => (
              <div key={agentId} className="flex justify-between">
                <span className="text-text/80">#{agentId}</span>
                <span className="text-neon-sell">{formatQty(qty)} lotes</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
