export const UBS_SHORT_NAME = "UBS";

export function roundToStep(value: number, step: number): number {
  if (!Number.isFinite(value) || step <= 0) return value;
  return Math.round(value / step) * step;
}

/**
 * VWAP do fluxo agressor do agente: (Σ p·q como comprador + Σ p·q como vendedor) / (volume total).
 * Usado para alinhar linhas de overlay ao eixo de preço do gráfico.
 */
export function computeAgentAggressorVwap(
  agentId: number,
  buyTotals: Record<number, number>,
  sellTotals: Record<number, number>,
  buyFinancial: Record<number, number>,
  sellFinancial: Record<number, number>,
): number | null {
  const bq = buyTotals[agentId] ?? 0;
  const sq = sellTotals[agentId] ?? 0;
  const tq = bq + sq;
  if (tq <= 0) return null;
  const bf = buyFinancial[agentId] ?? 0;
  const sf = sellFinancial[agentId] ?? 0;
  return (bf + sf) / tq;
}

/** Encontra o agentId cujo short name é UBS (ou nome contém UBS). */
export function findUbsAgentId(
  agentShortNames: Record<number, string>,
  agentNames: Record<number, string>,
): number | null {
  for (const [id, short] of Object.entries(agentShortNames)) {
    if (short === UBS_SHORT_NAME) return Number(id);
  }
  for (const [id, name] of Object.entries(agentNames)) {
    if (name.toUpperCase().includes(UBS_SHORT_NAME)) return Number(id);
  }
  return null;
}
