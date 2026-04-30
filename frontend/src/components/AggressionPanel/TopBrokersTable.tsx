import { useMemo } from "react";
import { useMarketStore } from "../../store/marketStore";
import {
  formatFinancialInt,
  formatPctOneDecimal,
  formatPrice,
  formatQty,
} from "../../utils/formatters";
import { isTauri } from "../../utils/tauri";
import { buildAgentSaldoRows } from "../../utils/agentVolume";

/** Verdes/vermelhos próximos ao Profit (Times & Trades / Saldo): texto forte + fundos da coluna Média. */
const SALDO = {
  finBuy: "text-[#00ff66]",
  finSell: "text-[#ff3344]",
  rowBuy: "bg-[#040806]",
  rowSell: "bg-[#080404]",
  medBuyBg: "bg-[#0d3020]",
  medSellBg: "bg-[#300d12]",
  medText: "text-[#f0f0f0]",
  border: "border-[#141414]",
  headerBg: "bg-[#050505]",
} as const;

export function TopBrokersTable() {
  const agentBuyTotals = useMarketStore((s) => s.agentBuyTotals);
  const agentSellTotals = useMarketStore((s) => s.agentSellTotals);
  const agentBuyFinancial = useMarketStore((s) => s.agentBuyFinancial);
  const agentSellFinancial = useMarketStore((s) => s.agentSellFinancial);
  const agentNames = useMarketStore((s) => s.agentNames);
  const agentShortNames = useMarketStore((s) => s.agentShortNames);
  const timesTradesLoading = useMarketStore((s) => s.timesTradesLoading);
  const timesTradesLoadingMessage = useMarketStore(
    (s) => s.timesTradesLoadingMessage,
  );

  const rows = useMemo(
    () =>
      buildAgentSaldoRows(
        agentBuyTotals,
        agentSellTotals,
        agentBuyFinancial,
        agentSellFinancial,
      ),
    [agentBuyTotals, agentSellTotals, agentBuyFinancial, agentSellFinancial],
  );

  /** No Tauri usa nome abreviado; no browser usa nome completo. Profit costuma exibir siglas em caixa alta. */
  const agentLabel = (agentId: number) => {
    const raw = isTauri()
      ? (agentShortNames[agentId] ?? agentNames[agentId] ?? `#${agentId}`)
      : (agentNames[agentId] ?? `#${agentId}`);
    return raw.trim().toUpperCase();
  };

  return (
    <div className="flex flex-col gap-1.5 min-h-0">
      <div className="flex items-start justify-between gap-3 px-0.5">
        <p className="text-[9px] text-zinc-500 leading-tight">
          % = participação no volume financeiro total (todas as corretoras). Ordem = Vol. Fin.
          líquido decrescente. Acumulado desde conexão / troca de ativo; zera ao mudar o dia
          (data no feed).
        </p>
        <span
          className={`shrink-0 min-w-[6.75rem] inline-flex items-center justify-end gap-1.5 text-[9px] font-semibold ${
            timesTradesLoading ? "text-amber-300" : "text-transparent"
          }`}
          aria-live="polite"
        >
          <span
            className={`h-2.5 w-2.5 rounded-full border-2 ${
              timesTradesLoading
                ? "border-amber-300/30 border-t-amber-300 animate-spin"
                : "border-transparent"
            }`}
            aria-hidden="true"
          />
          <span>{timesTradesLoading ? "Atualizando" : "Atualizado"}</span>
        </span>
      </div>
      <div
        className={`pq-saldo-scroll overflow-y-auto max-h-[min(48vh,360px)] border ${SALDO.border} bg-black`}
      >
        <table className="w-full border-collapse text-[11px] font-mono leading-tight tabular-nums">
          <thead className={`sticky top-0 z-10 ${SALDO.headerBg} border-b ${SALDO.border}`}>
            <tr className="text-zinc-500 uppercase tracking-wide">
              <th className="py-1 px-2 font-normal text-left text-[10px]">Corretora</th>
              <th className="py-1 px-2 font-normal text-right text-[10px] w-12">%</th>
              <th className="py-1 px-2 font-normal text-right text-[10px]">Vol. Fin.</th>
              <th className="py-1 px-2 font-normal text-right text-[10px]">Vol. Qtd</th>
              <th className="py-1 px-2 font-normal text-right text-[10px] min-w-[6.5rem]">
                Média
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="py-6 text-center text-zinc-600 align-middle text-xs"
                >
                  {timesTradesLoading ? (
                    <span className="inline-flex items-center justify-center gap-2 text-amber-300">
                      <span
                        className="h-3 w-3 rounded-full border-2 border-amber-300/30 border-t-amber-300 animate-spin"
                        aria-hidden="true"
                      />
                      <span>{timesTradesLoadingMessage || "Atualizando Times & Trades"}</span>
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ) : (
              rows.map(({ agentId, volQty, volFin, avgPrice, pct }) => {
                const finClass =
                  volFin > 0
                    ? SALDO.finBuy
                    : volFin < 0
                      ? SALDO.finSell
                      : "text-zinc-500";
                const qtyClass =
                  volQty > 0
                    ? SALDO.finBuy
                    : volQty < 0
                      ? SALDO.finSell
                      : "text-zinc-500";
                const rowBg =
                  volQty > 0 ? SALDO.rowBuy : volQty < 0 ? SALDO.rowSell : "bg-black";
                const medWrap =
                  volQty > 0
                    ? `${SALDO.medBuyBg} ${SALDO.medText}`
                    : volQty < 0
                      ? `${SALDO.medSellBg} ${SALDO.medText}`
                      : "bg-black text-zinc-500";

                return (
                  <tr
                    key={agentId}
                    className={`border-b ${SALDO.border} last:border-b-0 ${rowBg}`}
                  >
                    <td className="py-0.5 px-2 text-zinc-200 align-middle whitespace-nowrap">
                      {agentLabel(agentId)}
                    </td>
                    <td className="py-0.5 px-2 text-right text-zinc-300 align-middle">
                      {formatPctOneDecimal(pct)}
                    </td>
                    <td className={`py-0.5 px-2 text-right align-middle ${finClass}`}>
                      {formatFinancialInt(volFin)}
                    </td>
                    <td className={`py-0.5 px-2 text-right align-middle ${qtyClass}`}>
                      {formatQty(volQty)}
                    </td>
                    <td className={`py-0.5 px-2 text-right align-middle ${medWrap}`}>
                      {avgPrice != null && Number.isFinite(avgPrice)
                        ? formatPrice(avgPrice)
                        : "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
