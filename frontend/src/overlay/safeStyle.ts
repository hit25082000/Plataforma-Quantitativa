/** Valores seguros para atributos SVG / estilos (evita NaN, Infinity, null/undefined em runtime React). */

export function safeNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

/** Retorno em pixels numéricos (SVG), não string `"12px"`. */
export function safePx(value: unknown, fallback: number): number {
  return safeNumber(value, fallback);
}
