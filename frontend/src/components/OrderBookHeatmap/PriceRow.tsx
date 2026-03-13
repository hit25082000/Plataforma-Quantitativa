import { getHeatmapColor } from "../../utils/colors";
import { formatPrice, formatQty } from "../../utils/formatters";

interface PriceRowProps {
  price: number;
  qty: number;
  maxQty: number;
  isMid?: boolean;
  isWall?: boolean;
}

export function PriceRow({ price, qty, maxQty, isMid, isWall }: PriceRowProps) {
  const color = getHeatmapColor(qty);
  const widthPercent = maxQty > 0 ? Math.min(100, (qty / maxQty) * 100) : 0;

  return (
    <div className="flex items-center gap-2 py-0.5 font-mono text-sm">
      <span className="w-20 shrink-0 text-right text-text/90">{formatPrice(price)}</span>
      {isMid ? (
        <div className="flex-1 flex items-center justify-center text-text/50 text-xs border-t border-b border-[#4a4a4a] py-1">
          ─── {formatPrice(price)} ───
        </div>
      ) : (
        <>
          <div className="flex-1 h-5 min-w-[40px] bg-bg rounded overflow-hidden">
            <div
              className="h-full rounded transition-all duration-150"
              style={{
                width: `${widthPercent}%`,
                backgroundColor: color,
                border: isWall ? "1px solid #ff4400" : undefined,
              }}
            />
          </div>
          <span className="w-16 text-right text-text/70">{formatQty(qty)}</span>
        </>
      )}
    </div>
  );
}
