import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Agent007Panel } from "../Agent007/Agent007Panel";
import { useMarketStore } from "../../store/marketStore";
import { formatPrice, formatTs } from "../../utils/formatters";
import { AssetSelector } from "./AssetSelector";
import { RenkoBrickSelector } from "./RenkoBrickSelector";
import OverlayControl from "../OverlayControl";

interface StatusBarProps {
  onOpenSettings?: () => void;
}

export function StatusBar({ onOpenSettings }: StatusBarProps) {
  const wsStatus = useMarketStore((s) => s.wsStatus);
  const selectedTicker = useMarketStore((s) => s.selectedTicker);
  const vwap = useMarketStore((s) => s.vwap);
  const assetSwitchStatus = useMarketStore((s) => s.assetSwitchStatus);
  const assetSwitchMessage = useMarketStore((s) => s.assetSwitchMessage);
  const [time, setTime] = useState(formatTs(new Date().toISOString()));
  const [agent007Open, setAgent007Open] = useState(false);

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

  const handleCloseOverlay = async () => {
    try {
      await invoke("close_profit_overlay");
    } catch (err) {
      console.error("[overlay] close_profit_overlay failed:", err);
    }
  };

  return (
    <div className="flex items-center gap-6 px-4 py-2 bg-grid border-b border-border font-mono text-sm">
      <span className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${wsStatus === "connected" ? "bg-green-500" : wsStatus === "connecting" ? "bg-amber-400" : "bg-red-500"}`} />
        <span className={cfg.color}>{cfg.label}</span>
      </span>
      <div className="flex items-center gap-2 shrink-0">
        <AssetSelector currentTicker={selectedTicker} />
        <RenkoBrickSelector />
      </div>
      {assetSwitchStatus === "error" && assetSwitchMessage && (
        <span className="text-amber-400 text-xs max-w-[280px] truncate" title={assetSwitchMessage}>
          {assetSwitchMessage}
        </span>
      )}
      <span className="text-text/80">VWAP: {vwap > 0 ? formatPrice(vwap) : "—"}</span>
      <span className="text-text/60 ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={() => setAgent007Open(true)}
          className="px-2 py-1 rounded text-text/70 hover:text-text hover:bg-border/50 text-xs font-mono"
          title="Agente 007 — análise em tempo real"
        >
          007
        </button>
        <details className="relative">
          <summary
            className="list-none cursor-pointer px-2 py-1 rounded text-text/70 hover:text-text hover:bg-border/50 text-xs"
            title="Overlay OCR"
          >
            Overlay
          </summary>
          <div className="absolute right-0 top-7 z-50">
            <OverlayControl />
          </div>
        </details>
        <button
          onClick={handleCloseOverlay}
          className="px-2 py-1 rounded text-text/70 hover:text-text hover:bg-border/50 text-xs"
          title="Fechar janela de overlay"
        >
          Fechar overlay
        </button>
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

      {agent007Open && (
        <div className="fixed inset-0 z-[100] flex justify-end">
          <button
            type="button"
            className="flex-1 bg-black/50 border-0 cursor-default"
            aria-label="Fechar painel"
            onClick={() => setAgent007Open(false)}
          />
          <div className="w-full max-w-md h-full bg-grid border-l border-border shadow-xl flex flex-col min-h-0">
            <div className="shrink-0 flex justify-end border-b border-border px-2 py-1">
              <button
                type="button"
                onClick={() => setAgent007Open(false)}
                className="px-3 py-1 text-xs text-text/60 hover:text-text"
              >
                Fechar
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <Agent007Panel />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
