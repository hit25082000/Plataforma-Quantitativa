import { useRef, useMemo } from "react";
import type { DomLevel } from "../types/messages";

const WINDOW_SIZE = 60;
const DRY_THRESHOLD = 0.35; // 35% reduction → secagem

function sumQty(levels: DomLevel[]): number {
  return levels.reduce((s, l) => s + l.qty, 0);
}

export type SecagemSignal = "compra" | "venda" | null;

export function useSecagemDetection(
  domBuy: DomLevel[],
  domSell: DomLevel[],
  lastPrice: number
): SecagemSignal {
  const historyRef = useRef<{ price: number; buyTotal: number; sellTotal: number }[]>([]);
  const lastKeyRef = useRef<string>("");

  return useMemo(() => {
    const buyTotal = sumQty(domBuy);
    const sellTotal = sumQty(domSell);

    if (lastPrice <= 0 && buyTotal === 0 && sellTotal === 0) return null;

    const key = `${lastPrice}|${buyTotal}|${sellTotal}`;
    if (key !== lastKeyRef.current) {
      lastKeyRef.current = key;
      const history = historyRef.current;
      history.push({ price: lastPrice, buyTotal, sellTotal });
      if (history.length > WINDOW_SIZE) history.shift();
    }

    const history = historyRef.current;
    if (history.length < 10) return null;

    const prices = history.map((h) => h.price);
    const buyTotals = history.map((h) => h.buyTotal);
    const sellTotals = history.map((h) => h.sellTotal);

    const recentHigh = Math.max(...prices);
    const recentLow = Math.min(...prices);
    const peakBuy = Math.max(...buyTotals);
    const peakSell = Math.max(...sellTotals);

    const atTop = lastPrice >= recentHigh && recentHigh > recentLow;
    const atBottom = lastPrice <= recentLow && recentLow < recentHigh;

    if (atTop && peakBuy > 0 && buyTotal <= (1 - DRY_THRESHOLD) * peakBuy) {
      return "compra";
    }
    if (atBottom && peakSell > 0 && sellTotal <= (1 - DRY_THRESHOLD) * peakSell) {
      return "venda";
    }
    return null;
  }, [domBuy, domSell, lastPrice]);
}
