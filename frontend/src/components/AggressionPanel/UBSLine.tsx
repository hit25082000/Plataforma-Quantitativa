import { useMarketStore } from "../../store/marketStore";
import { formatQty } from "../../utils/formatters";
import { AGGRESSION_STEP } from "../../store/marketStore";

const UBS_SHORT_NAME = "UBS";

function roundToStep(value: number, step: number): number {
  return Math.round(value / step) * step;
}

/** Encontra o agentId cujo short name é UBS (ou nome contém UBS). */
function findUbsAgentId(
  agentShortNames: Record<number, string>,
  agentNames: Record<number, string>
): number | null {
  for (const [id, short] of Object.entries(agentShortNames)) {
    if (short === UBS_SHORT_NAME) return Number(id);
  }
  for (const [id, name] of Object.entries(agentNames)) {
    if (name.toUpperCase().includes(UBS_SHORT_NAME)) return Number(id);
  }
  return null;
}

export function UBSLine() {
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);
  const agentShortNames = useMarketStore((s) => s.agentShortNames);
  const agentNames = useMarketStore((s) => s.agentNames);
  const flowInversions = useMarketStore((s) => s.flowInversions);

  const ubsId = findUbsAgentId(agentShortNames, agentNames);
  if (ubsId == null) {
    return (
      <div className="rounded border border-border/50 bg-bg/50 px-3 py-2">
        <p className="text-xs text-text/60">UBS — aguardando dados (nenhum trade UBS ainda)</p>
      </div>
    );
  }

  const buy = agentBuyTotals[ubsId] ?? 0;
  const sell = agentSellTotals[ubsId] ?? 0;
  const net = buy - sell;
  const buyRounded = roundToStep(buy, AGGRESSION_STEP);
  const sellRounded = roundToStep(sell, AGGRESSION_STEP);
  const netRounded = roundToStep(net, AGGRESSION_STEP);

  const ubsInversions = flowInversions.filter((m) => m.agent_name === UBS_SHORT_NAME).slice(0, 3);

  return (
    <div className="rounded border border-border/50 bg-bg/50 px-3 py-2 space-y-1">
      <h3 className="text-xs font-semibold text-text/60 mb-1.5">UBS — posição</h3>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-sm">
        <span className="text-text/80">Compra</span>
        <span className="text-neon-buy">{formatQty(buyRounded)}</span>
        <span className="text-text/40">|</span>
        <span className="text-text/80">Venda</span>
        <span className="text-neon-sell">{formatQty(sellRounded)}</span>
        <span className="text-text/40">|</span>
        <span className="text-text/80">Saldo</span>
        <span className={netRounded >= 0 ? "text-neon-buy" : "text-neon-sell"}>
          {netRounded >= 0 ? "+" : ""}{formatQty(netRounded)}
        </span>
      </div>
      {ubsInversions.length > 0 && (
        <div className="pt-1 border-t border-border/30">
          <p className="text-[10px] text-text/50 mb-0.5">Últimas inversões de fluxo (UBS)</p>
          <ul className="space-y-0.5 font-mono text-[10px] text-text/70">
            {ubsInversions.map((inv, i) => (
              <li key={i}>
                Δ anterior: {inv.previous_delta} → atual: {inv.current_delta}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
