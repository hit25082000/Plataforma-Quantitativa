export function formatPrice(price: number): string {
  return price.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatTs(ts: string): string {
  try {
    const date = new Date(ts);
    return date.toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

export function formatQty(qty: number): string {
  return qty.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

/** Volume financeiro (saldo / painéis): inteiro, pt-BR. */
export function formatFinancialInt(n: number): string {
  return Math.round(n).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

/** Percentual com uma casa decimal (pt-BR). */
export function formatPctOneDecimal(n: number): string {
  return n.toLocaleString("pt-BR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

export function formatRelativeTime(ts: string): string {
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);

    if (diffSec < 5) return "agora";
    if (diffSec < 60) return `há ${diffSec}s`;
    if (diffMin < 60) return `há ${diffMin}min`;
    return formatTs(ts);
  } catch {
    return ts;
  }
}
