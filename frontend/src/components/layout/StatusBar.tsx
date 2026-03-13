import { useState, useEffect } from "react";
import { useMarketStore } from "../../store/marketStore";
import { formatPrice, formatTs } from "../../utils/formatters";
import { AssetSelector } from "./AssetSelector";

interface StatusBarProps {
  onOpenSettings?: () => void;
}

export function StatusBar({ onOpenSettings }: StatusBarProps) {
  const wsStatus = useMarketStore((s) => s.wsStatus);
  const selectedTicker = useMarketStore((s) => s.selectedTicker);
  const vwap = useMarketStore((s) => s.vwap);
  const [time, setTime] = useState(formatTs(new Date().toISOString()));

  useEffect(() => {
    const id = setInterval(() => {
      setTime(formatTs(new Date().toISOString()));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const statusConfig = {
    connecting: { label: "CONECTANDO", color: "text-amber-400 animate-pulse" },
    connected: { label: "CONECTADO", color: "text-green-500" },
    disconnected: { label: "DESCONECTADO", color: "text-red-500" },
  };

  const cfg = statusConfig[wsStatus];

  return (
    <div className="flex items-center gap-6 px-4 py-2 bg-grid border-b border-border font-mono text-sm">
      <span className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${wsStatus === "connected" ? "bg-green-500" : wsStatus === "connecting" ? "bg-amber-400" : "bg-red-500"}`} />
        <span className={cfg.color}>{cfg.label}</span>
      </span>
      <AssetSelector currentTicker={selectedTicker} />
      <span className="text-text/80">VWAP: {vwap > 0 ? formatPrice(vwap) : "—"}</span>
      <span className="text-text/60 ml-auto flex items-center gap-2">
        {onOpenSettings && (
          <button
            onClick={onOpenSettings}
            className="px-2 py-1 rounded text-text/60 hover:text-text hover:bg-border/50 text-xs"
            title="Configurações"
          >
            ⚙
          </button>
        )}
        {time}
      </span>
    </div>
  );
}
