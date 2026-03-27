export interface AgentVolQtyRow {
  agentId: number;
  volQty: number;
}

export interface AgentDirectVolQtyRow {
  agentId: number;
  volQty: number;
  directVolByQty: number;
}

/** Linha estilo aba Saldo (Profit): saldo líquido por corretora, ordenado por Vol. Fin. */
export interface AgentSaldoRow {
  agentId: number;
  /** Σ qtd compradora − Σ qtd vendedora */
  volQty: number;
  /** Σ fin comprador − Σ fin vendedor */
  volFin: number;
  /** volFin / volQty quando volQty ≠ 0 */
  avgPrice: number | null;
  /**
   * Participação no volume financeiro total do ativo (Σ buyFin+sellFin de todas as corretoras
   * com negócio), como a coluna % do Profit — não some 100% nas linhas visíveis.
   */
  pct: number;
}

export function collectAgentIds(
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

function collectAgentIdsFromFourMaps(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
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
  for (const rawId of Object.keys(buyFinancial)) {
    const id = Number(rawId);
    if (Number.isFinite(id)) ids.add(id);
  }
  for (const rawId of Object.keys(sellFinancial)) {
    const id = Number(rawId);
    if (Number.isFinite(id)) ids.add(id);
  }
  return [...ids];
}

/**
 * Profit (Times & Trades) - Vol. Qtd líquido por corretora:
 * Σ quantidade como compradora - Σ quantidade como vendedora.
 */
export function computeAgentVolQty(
  agentId: number,
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
): number {
  const buy = Number(buyTotals[agentId] ?? 0);
  const sell = Number(sellTotals[agentId] ?? 0);
  if (!Number.isFinite(buy) || !Number.isFinite(sell)) return 0;
  return buy - sell;
}

/**
 * Times & Trades (Nelogica) - opção de média "Direto Vol./Quantidade":
 * (volume financeiro / volume quantidade) / fator multiplicador.
 *
 * Como o fator multiplicador é constante para o ativo selecionado,
 * ele não altera a ordenação do ranking entre corretoras.
 */
export function computeDirectVolByQty(
  financialVolume: number,
  qtyVolume: number,
  multiplier: number,
): number {
  if (!Number.isFinite(financialVolume) || !Number.isFinite(qtyVolume)) return 0;
  if (qtyVolume === 0 || !Number.isFinite(multiplier) || multiplier <= 0) return 0;
  return financialVolume / qtyVolume / multiplier;
}

export function getTopAgentsByVolQty(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  n: number,
): { topBuyers: AgentVolQtyRow[]; topSellers: AgentVolQtyRow[] } {
  const rows: AgentVolQtyRow[] = collectAgentIds(buyTotals, sellTotals).map(
    (agentId) => ({
      agentId,
      volQty: computeAgentVolQty(agentId, buyTotals, sellTotals),
    }),
  );

  const topBuyers = rows
    .filter((r) => r.volQty > 0)
    .sort((a, b) => b.volQty - a.volQty)
    .slice(0, n);

  const topSellers = rows
    .filter((r) => r.volQty < 0)
    .sort((a, b) => a.volQty - b.volQty)
    .slice(0, n);

  return { topBuyers, topSellers };
}

export function getTopAgentsByDirectVolQty(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
  n: number,
  multiplier: number = 1,
): { topBuyers: AgentDirectVolQtyRow[]; topSellers: AgentDirectVolQtyRow[] } {
  const rows: AgentDirectVolQtyRow[] = collectAgentIds(buyTotals, sellTotals).map(
    (agentId) => {
      const buyQty = Number(buyTotals[agentId] ?? 0);
      const sellQty = Number(sellTotals[agentId] ?? 0);
      const buyFin = Number(buyFinancial[agentId] ?? 0);
      const sellFin = Number(sellFinancial[agentId] ?? 0);

      const volQty = computeAgentVolQty(agentId, buyTotals, sellTotals);
      const directVolByQty = computeDirectVolByQty(
        buyFin - sellFin,
        volQty,
        multiplier,
      );

      return { agentId, volQty, directVolByQty };
    },
  );

  const topBuyers = rows
    .filter((r) => r.volQty > 0)
    .sort((a, b) => b.directVolByQty - a.directVolByQty)
    .slice(0, n);

  const topSellers = rows
    .filter((r) => r.volQty < 0)
    .sort((a, b) => a.directVolByQty - b.directVolByQty)
    .slice(0, n);

  return { topBuyers, topSellers };
}

/**
 * Tabela Saldo (Profit): uma lista ordenada por Vol. Fin. decrescente
 * (maior comprador líquido no topo; vendedores líquidos com volFin mais negativo embaixo).
 */
export function buildAgentSaldoRows(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
): AgentSaldoRow[] {
  const allIds = collectAgentIdsFromFourMaps(
    buyTotals,
    sellTotals,
    buyFinancial,
    sellFinancial,
  );

  let totalGrossFinAllAgents = 0;
  for (const agentId of allIds) {
    const buyFin = Number(buyFinancial[agentId] ?? 0);
    const sellFin = Number(sellFinancial[agentId] ?? 0);
    if (Number.isFinite(buyFin) && Number.isFinite(sellFin)) {
      totalGrossFinAllAgents += buyFin + sellFin;
    }
  }

  const raw: Omit<AgentSaldoRow, "pct">[] = allIds.map((agentId) => {
    const buyQty = Number(buyTotals[agentId] ?? 0);
    const sellQty = Number(sellTotals[agentId] ?? 0);
    const buyFin = Number(buyFinancial[agentId] ?? 0);
    const sellFin = Number(sellFinancial[agentId] ?? 0);
    const volQty = buyQty - sellQty;
    const volFin = buyFin - sellFin;
    const avgPrice =
      volQty !== 0 && Number.isFinite(volFin) && Number.isFinite(volQty)
        ? volFin / volQty
        : null;
    return { agentId, volQty, volFin, avgPrice };
  });

  const filtered = raw.filter((r) => r.volQty !== 0 || r.volFin !== 0);
  /** Ordem Profit: Vol. Fin. decrescente; empate → id estável. */
  filtered.sort((a, b) => {
    const d = b.volFin - a.volFin;
    if (d !== 0) return d;
    return a.agentId - b.agentId;
  });

  return filtered.map((r) => {
    const buyFin = Number(buyFinancial[r.agentId] ?? 0);
    const sellFin = Number(sellFinancial[r.agentId] ?? 0);
    const grossFin =
      Number.isFinite(buyFin) && Number.isFinite(sellFin) ? buyFin + sellFin : 0;
    return {
      ...r,
      pct:
        totalGrossFinAllAgents > 0
          ? (grossFin / totalGrossFinAllAgents) * 100
          : 0,
    };
  });
}

/** Líder por saldo financeiro líquido comprador (volFin > 0 máximo). */
export function topBuyerByVolFin(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
): number | null {
  let bestId: number | null = null;
  let bestFin = 0;
  for (const id of collectAgentIdsFromFourMaps(
    buyTotals,
    sellTotals,
    buyFinancial,
    sellFinancial,
  )) {
    const buyFin = Number(buyFinancial[id] ?? 0);
    const sellFin = Number(sellFinancial[id] ?? 0);
    const volFin = buyFin - sellFin;
    if (volFin > bestFin) {
      bestFin = volFin;
      bestId = id;
    }
  }
  return bestFin > 0 ? bestId : null;
}

/** Líder por saldo financeiro líquido vendedor (volFin < 0 mínimo). */
export function topSellerByVolFin(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
): number | null {
  let bestId: number | null = null;
  let bestFin = 0;
  for (const id of collectAgentIdsFromFourMaps(
    buyTotals,
    sellTotals,
    buyFinancial,
    sellFinancial,
  )) {
    const buyFin = Number(buyFinancial[id] ?? 0);
    const sellFin = Number(sellFinancial[id] ?? 0);
    const volFin = buyFin - sellFin;
    if (volFin < bestFin) {
      bestFin = volFin;
      bestId = id;
    }
  }
  return bestFin < 0 ? bestId : null;
}

/** Preço médio do saldo líquido (Vol. Fin. / Vol. Qtd), como na coluna Média do Profit. */
export function netSaldoAvgPrice(
  agentId: number,
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
): number | null {
  const volQty = computeAgentVolQty(agentId, buyTotals, sellTotals);
  const buyFin = Number(buyFinancial[agentId] ?? 0);
  const sellFin = Number(sellFinancial[agentId] ?? 0);
  const volFin = buyFin - sellFin;
  if (volQty === 0 || !Number.isFinite(volFin) || !Number.isFinite(volQty)) return null;
  return volFin / volQty;
}

export function topBuyerByVolQty(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
): number | null {
  let bestId: number | null = null;
  let bestVolQty = 0;
  for (const id of collectAgentIds(buyTotals, sellTotals)) {
    const volQty = computeAgentVolQty(id, buyTotals, sellTotals);
    if (volQty > bestVolQty) {
      bestVolQty = volQty;
      bestId = id;
    }
  }
  return bestId;
}

export function topSellerByVolQty(
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
): number | null {
  let bestId: number | null = null;
  let bestVolQty = 0;
  for (const id of collectAgentIds(buyTotals, sellTotals)) {
    const volQty = computeAgentVolQty(id, buyTotals, sellTotals);
    if (volQty < bestVolQty) {
      bestVolQty = volQty;
      bestId = id;
    }
  }
  return bestId;
}
