import { useMarketStore } from "../../store/marketStore";
import { formatQty } from "../../utils/formatters";

export function BuyVsSellBar() {
  const totalBuy = useMarketStore((s) => s.totalBuyAggression);
  const totalSell = useMarketStore((s) => s.totalSellAggression);

  const total = totalBuy + totalSell || 1;
  const buyPercent = (totalBuy / total) * 100;
  const sellPercent = (totalSell / total) * 100;

  const net = totalBuy - totalSell;
  const isPositive = net >= 0;

  return (
    <div className="space-y-2">
      <div className="text-2xl font-mono font-semibold">
        <span className={isPositive ? "text-neon-buy" : "text-neon-sell"}>
          NET: {isPositive ? "+" : ""}{formatQty(net)} {isPositive ? "▲" : "▼"}
        </span>
      </div>
      <div className="flex h-4 rounded overflow-hidden bg-bg">
        <div
          className="transition-all duration-300"
          style={{
            width: `${buyPercent}%`,
            backgroundColor: "#00ff8844",
          }}
        />
        <div
          className="transition-all duration-300"
          style={{
            width: `${sellPercent}%`,
            backgroundColor: "#ff224444",
          }}
        />
      </div>
      <div className="flex justify-between text-sm text-text/70 font-mono">
        <span>Buy {formatQty(totalBuy)}</span>
        <span>|</span>
        <span>Sell {formatQty(totalSell)}</span>
      </div>
    </div>
  );
}
