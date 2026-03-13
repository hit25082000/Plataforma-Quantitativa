import { useState, useRef, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useMarketStore } from "../../store/marketStore";
import { isTauri } from "../../utils/tauri";

// Lista de ativos disponíveis (futuros B3)
const AVAILABLE_TICKERS = [
  { symbol: "TESTE", exchange: "SIM", label: "Ativo Mock (teste)" },
  { symbol: "WINFUT", exchange: "BMF", label: "Mini Índice Contínuo" },
  { symbol: "WDOFUT", exchange: "BMF", label: "Mini Dólar Contínuo" },
  { symbol: "INDFUT", exchange: "BMF", label: "Índice Cheio Contínuo" },
  { symbol: "DOLFUT", exchange: "BMF", label: "Dólar Cheio Contínuo" },
  { symbol: "PETR4",  exchange: "BOVESPA", label: "Petrobras PN (PETR4)" },
  { symbol: "VALE3",  exchange: "BOVESPA", label: "Vale ON (VALE3)" },
  { symbol: "ITUB4",  exchange: "BOVESPA", label: "Itaú PN (ITUB4)" },
  { symbol: "BBDC4",  exchange: "BOVESPA", label: "Bradesco PN (BBDC4)" },
  { symbol: "B3SA3",  exchange: "BOVESPA", label: "B3 ON (B3SA3)" },
  { symbol: "ABEV3",  exchange: "BOVESPA", label: "Ambev ON (ABEV3)" },
];

interface AssetSelectorProps {
  currentTicker: string;
}

export function AssetSelector({ currentTicker }: AssetSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const setSelectedTicker = useMarketStore((s) => s.setSelectedTicker);
  const setAssetSwitchStatus = useMarketStore((s) => s.setAssetSwitchStatus);
  const clearMarketData = useMarketStore((s) => s.clearMarketData);

  // Fechar ao clicar fora
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const filtered = AVAILABLE_TICKERS.filter(
    (t) =>
      t.symbol.toLowerCase().includes(search.toLowerCase()) ||
      t.label.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelect = async (ticker: typeof AVAILABLE_TICKERS[0]) => {
    const label = `${ticker.symbol} · ${ticker.exchange}`;
    setSelectedTicker(label);
    setIsOpen(false);
    setSearch("");

    if (isTauri()) {
      setAssetSwitchStatus("switching");
      clearMarketData();
      try {
        const result = await invoke<{ success: boolean; message: string }>("set_active_asset", {
          ticker: ticker.symbol,
          exchange: ticker.exchange,
        });
        setAssetSwitchStatus(result.success ? "active" : "error");
        if (!result.success) {
          console.warn("Troca de ativo:", result.message);
        }
      } catch (e) {
        setAssetSwitchStatus("error");
        console.warn("Erro ao trocar ativo:", e);
      }
    }
  };

  // Extrair apenas o símbolo do ticker ativo (sem a bolsa)
  const displayTicker = currentTicker.split(" · ")[0] || currentTicker;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md
                   bg-bg/60 border border-border/50 hover:border-border
                   text-text/90 hover:text-text transition-all duration-150
                   text-sm font-semibold tracking-wide"
      >
        <span className="text-emerald-400 text-xs">●</span>
        {displayTicker}
        <svg className={`w-3 h-3 text-text/50 transition-transform ${isOpen ? "rotate-180" : ""}`}
             fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 w-72 z-50
                        bg-grid border border-border rounded-lg shadow-2xl shadow-black/40
                        overflow-hidden animate-in fade-in slide-in-from-top-1">
          {/* Busca */}
          <div className="p-2 border-b border-border/60">
            <input
              type="text"
              placeholder="Buscar ativo..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              className="w-full px-3 py-1.5 rounded bg-bg border border-border/40
                         text-text text-sm placeholder-text/30
                         focus:outline-none focus:border-emerald-500/50"
            />
          </div>

          {/* Lista */}
          <div className="max-h-64 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="text-text/40 text-sm text-center py-4">Nenhum ativo encontrado</p>
            ) : (
              filtered.map((t) => {
                const isActive = currentTicker.startsWith(t.symbol);
                return (
                  <button
                    key={t.symbol}
                    onClick={() => handleSelect(t)}
                    className={`w-full text-left px-3 py-2 flex items-center gap-3 text-sm
                                hover:bg-emerald-500/10 transition-colors
                                ${isActive ? "bg-emerald-500/15 text-emerald-300" : "text-text/80"}`}
                  >
                    <span className="font-mono font-semibold w-16">{t.symbol}</span>
                    <span className="text-text/50 text-xs flex-1">{t.label}</span>
                    <span className="text-text/30 text-[10px] uppercase">{t.exchange}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
