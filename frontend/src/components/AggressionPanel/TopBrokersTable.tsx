import { useMarketStore } from "../../store/marketStore";
import { formatQty } from "../../utils/formatters";
import { isTauri } from "../../utils/tauri";

interface AgentNetQty {
  agentId: number;
  netQty: number;
}

function collectAgentIds(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
): number[] {
  const ids = new Set<number>();
  for (const rawId of Object.keys(buyTotals)) {
    const id = Number(rawId);
    if (Number.isFinite(id)) ids.add(id);
  }
  for (const rawId of Object.keys(sellTotals)) {
    const id = Number(rawId);
    if (Number.isFinite(id)) ids.add(id);
  }
  return [...ids];
}

function getTopByNet(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  n: number,
) {
  const rows: AgentNetQty[] = collectAgentIds(buyTotals, sellTotals).map((agentId) => {
    const buy = Number(buyTotals[agentId] ?? 0);
    const sell = Number(sellTotals[agentId] ?? 0);
    const netQty = Number.isFinite(buy) && Number.isFinite(sell) ? buy - sell : 0;
    return { agentId, netQty };
  });

  const topBuyers = rows
    .filter((r) => r.netQty > 0)
    .sort((a, b) => b.netQty - a.netQty)
    .slice(0, n);

  const topSellers = rows
    .filter((r) => r.netQty < 0)
    .sort((a, b) => a.netQty - b.netQty)
    .slice(0, n);

  return { topBuyers, topSellers };
}

export function TopBrokersTable() {
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);
  const agentNames = useMarketStore((s) => s.agentNames);
  const agentShortNames = useMarketStore((s) => s.agentShortNames);

  const { topBuyers, topSellers } = getTopByNet(
    agentBuyTotals,
    agentSellTotals,
    5,
  );
  /** No Tauri usa nome abreviado; no browser usa nome completo. */
  const agentLabel = (agentId: number) =>
    isTauri()
      ? (agentShortNames[agentId] ?? agentNames[agentId] ?? `#${agentId}`)
      : (agentNames[agentId] ?? `#${agentId}`);

  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h3 className="text-xs font-semibold text-text/60 mb-2">Top Compradores</h3>
        <div className="space-y-1 font-mono text-sm">
          {topBuyers.length === 0 ? (
            <p className="text-text/40">—</p>
          ) : (
            topBuyers.map(({ agentId, netQty }) => (
              <div key={agentId} className="flex justify-between">
                <span className="text-text/80">{agentLabel(agentId)}</span>
                <span className="text-neon-buy">+{formatQty(netQty)} lotes</span>
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
            topSellers.map(({ agentId, netQty }) => (
              <div key={agentId} className="flex justify-between">
                <span className="text-text/80">{agentLabel(agentId)}</span>
                <span className="text-neon-sell">{formatQty(netQty)} lotes</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
