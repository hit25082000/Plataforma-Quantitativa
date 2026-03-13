import { useDeferredValue } from "react";
import { useMarketStore } from "../../store/marketStore";
import { PriceRow } from "./PriceRow";

export function OrderBookHeatmap() {
  const domBuy = useMarketStore((s) => s.domBuy);
  const domSell = useMarketStore((s) => s.domSell);
  const lastPrice = useMarketStore((s) => s.lastPrice);
  const wallPriceByOfferId = useMarketStore((s) => s.wallPriceByOfferId);

  const deferredBuy = useDeferredValue(domBuy);
  const deferredSell = useDeferredValue(domSell);

  const wallPrices = new Set(Object.values(wallPriceByOfferId));

  const allQtys = [...deferredBuy, ...deferredSell].map((l) => l.qty);
  const maxQty = allQtys.length > 0 ? Math.max(...allQtys) : 1;

  const sellSorted = [...deferredSell].sort((a, b) => b.price - a.price);
  const buySorted = [...deferredBuy].sort((a, b) => b.price - a.price);

  const midIdx = sellSorted.findIndex((l) => l.price <= lastPrice);
  const showMid = lastPrice > 0 && midIdx >= 0;

  return (
    <div className="h-full flex flex-col">
      <h2 className="px-4 py-2 text-sm font-semibold text-text/80 border-b border-border shrink-0">
        ORDER BOOK HEATMAP
      </h2>
      <div className="flex-1 overflow-y-auto p-3 space-y-1">
        {sellSorted.length === 0 && buySorted.length === 0 ? (
          <p className="text-text/40 text-sm text-center py-8">Aguardando livro...</p>
        ) : (
          <>
            {sellSorted.map((level) => (
              <PriceRow
                key={`sell-${level.price}`}
                price={level.price}
                qty={level.qty}
                maxQty={maxQty}
                isWall={wallPrices.has(level.price)}
              />
            ))}
            {showMid && (
              <PriceRow
                price={lastPrice}
                qty={0}
                maxQty={maxQty}
                isMid
              />
            )}
            {buySorted.map((level) => (
              <PriceRow
                key={`buy-${level.price}`}
                price={level.price}
                qty={level.qty}
                maxQty={maxQty}
                isWall={wallPrices.has(level.price)}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
