import { useState, useEffect, useMemo } from "react";
import { Agent007Panel } from "../Agent007/Agent007Panel";
import { VoiceCopilotPanel } from "../VoiceCopilot/VoiceCopilotPanel";
import { useMarketStore } from "../../store/marketStore";
import { formatPrice, formatTs } from "../../utils/formatters";
import { AssetSelector } from "./AssetSelector";
import { RenkoBrickSelector } from "./RenkoBrickSelector";
import OverlayControl from "../OverlayControl";
import { distributorApiBase } from "../../config/distributorApi";

const STALE_ASSET_MS = 15_000;
const OUT_OF_SESSION_MIN_STALE_MS = 5 * 60_000;
const DISTRIBUTOR_POLL_MS = 2_000;

interface DistributorProbeState {
  healthOk: boolean;
  ready: boolean;
  feedLive: boolean | null;
  ipcStatus: string | null;
  wsClients: number | null;
  lastMarketEventAt: string | null;
  lastError: string | null;
}

type TransportUiState =
  | "disconnected"
  | "initializing"
  | "awaiting_feed"
  | "connected";

function parseSelectedAsset(label: string): { symbol: string; exchange: string } {
  const parts = label.split("·").map((p) => p.trim());
  return {
    symbol: parts[0] ?? "",
    exchange: parts[1] ?? "",
  };
}

function normalizeTickerSymbol(value: string): string {
  return value
    .split("·")[0]
    ?.trim()
    .toUpperCase()
    .replace(/\s+/g, "") ?? "";
}

function parseIsoMs(value: string | null | undefined): number {
  if (!value) return Number.NaN;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : Number.NaN;
}

function isLikelyOutOfSession(exchange: string, now: Date): boolean {
  if (exchange === "SIM") return false;
  const day = now.getDay();
  if (day === 0 || day === 6) return true;
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (exchange === "BMF") return minutes < 9 * 60 || minutes > 18 * 60 + 30;
  if (exchange === "BOVESPA") return minutes < 10 * 60 || minutes > 17 * 60 + 55;
  return minutes < 9 * 60 || minutes > 18 * 60;
}

interface StatusBarProps {
  onOpenSettings?: () => void;
}

export function StatusBar({ onOpenSettings }: StatusBarProps) {
  const selectedTicker = useMarketStore((s) => s.selectedTicker);
  const streamingTicker = useMarketStore((s) => s.streamingTicker);
  const lastMarketEventTs = useMarketStore((s) => s.lastMarketEventTs);
  const wsStatus = useMarketStore((s) => s.wsStatus);
  const vpOverlay = useMarketStore((s) => s.vpOverlay);
  const overlayLastUpdateTs = useMarketStore((s) => s.overlayLastUpdateTs);
  const vwap = useMarketStore((s) => s.vwap);
  const assetSwitchStatus = useMarketStore((s) => s.assetSwitchStatus);
  const assetSwitchMessage = useMarketStore((s) => s.assetSwitchMessage);
  const timesTradesLoading = useMarketStore((s) => s.timesTradesLoading);
  const timesTradesLoadingMessage = useMarketStore(
    (s) => s.timesTradesLoadingMessage,
  );
  const [time, setTime] = useState(formatTs(new Date().toISOString()));
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [agent007Open, setAgent007Open] = useState(false);
  const [copilotoOpen, setCopilotoOpen] = useState(false);
  const [probe, setProbe] = useState<DistributorProbeState>({
    healthOk: false,
    ready: false,
    feedLive: null,
    ipcStatus: null,
    wsClients: null,
    lastMarketEventAt: null,
    lastError: null,
  });

  useEffect(() => {
    const id = setInterval(() => {
      const iso = new Date().toISOString();
      setTime(formatTs(iso));
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timerId: ReturnType<typeof setTimeout> | null = null;
    const base = distributorApiBase();

    const safeFetchJson = async (path: string): Promise<unknown> => {
      const response = await fetch(`${base}${path}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`${path} -> HTTP ${response.status}`);
      }
      return response.json();
    };

    const poll = async () => {
      try {
        const health = (await safeFetchJson("/health")) as Record<string, unknown>;
        let ready = false;
        let feedLive: boolean | null = null;
        let ipcStatus: string | null = null;
        let wsClients: number | null = null;
        let lastMarketEventAt: string | null = null;
        let lastError: string | null = null;

        try {
          const readyResponse = await fetch(`${base}/ready`, {
            cache: "no-store",
          });
          const readyBody = (await readyResponse.json()) as Record<string, unknown>;
          ready = readyBody.ready === true;
          feedLive =
            typeof readyBody.feed_live === "boolean"
              ? readyBody.feed_live
              : null;
          ipcStatus =
            typeof readyBody.ipc_status === "string"
              ? readyBody.ipc_status
              : null;
        } catch {
          ready = false;
          feedLive = null;
        }

        try {
          const debug = (await safeFetchJson("/debug/status")) as Record<
            string,
            unknown
          >;
          wsClients =
            typeof debug.ws_clients === "number" &&
            Number.isFinite(debug.ws_clients)
              ? Math.max(0, Math.round(debug.ws_clients))
              : null;
          lastMarketEventAt =
            typeof debug.last_market_event_at === "string"
              ? debug.last_market_event_at
              : null;
          if (feedLive == null && typeof debug.feed_live === "boolean") {
            feedLive = debug.feed_live;
          }
          lastError =
            typeof debug.error === "string"
              ? debug.error
              : typeof debug.last_error === "string"
                ? debug.last_error
                : null;
        } catch {
          wsClients =
            typeof health.ws_clients === "number" &&
            Number.isFinite(health.ws_clients)
              ? Math.max(0, Math.round(health.ws_clients))
              : null;
          lastMarketEventAt =
            typeof health.last_market_event_at === "string"
              ? health.last_market_event_at
              : null;
          if (feedLive == null && typeof health.feed_live === "boolean") {
            feedLive = health.feed_live;
          }
          lastError =
            typeof health.last_error === "string" ? health.last_error : null;
        }

        if (!cancelled) {
          setProbe({
            healthOk: true,
            ready,
            feedLive,
            ipcStatus,
            wsClients,
            lastMarketEventAt,
            lastError,
          });
        }
      } catch {
        if (!cancelled) {
          setProbe((prev) => ({
            ...prev,
            healthOk: false,
            ready: false,
            feedLive: null,
          }));
        }
      } finally {
        if (!cancelled) {
          timerId = setTimeout(poll, DISTRIBUTOR_POLL_MS);
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timerId != null) {
        clearTimeout(timerId);
      }
    };
  }, []);

  const latestMarketEventMs = useMemo(() => {
    const fromStore = parseIsoMs(lastMarketEventTs);
    if (Number.isFinite(fromStore)) return fromStore;
    return parseIsoMs(probe.lastMarketEventAt);
  }, [lastMarketEventTs, probe.lastMarketEventAt]);

  const transportState = useMemo<TransportUiState>(() => {
    if (!probe.healthOk) return "disconnected";
    if (!probe.ready) return "initializing";
    if (wsStatus !== "connected") return "awaiting_feed";
    if (!Number.isFinite(latestMarketEventMs)) return "awaiting_feed";
    const ageMs = Math.max(0, nowMs - latestMarketEventMs);
    if (ageMs > STALE_ASSET_MS) {
      return "awaiting_feed";
    }
    if (probe.feedLive === false) return "awaiting_feed";
    return "connected";
  }, [latestMarketEventMs, nowMs, probe.feedLive, probe.healthOk, probe.ready, wsStatus]);

  const statusConfig = {
    initializing: {
      label: "INICIALIZANDO DISTRIBUTOR",
      color: "text-amber-400 animate-pulse",
    },
    awaiting_feed: { label: "AGUARDANDO FEED", color: "text-amber-300" },
    connected: { label: "CONECTADO", color: "text-green-500" },
    disconnected: { label: "DESCONECTADO", color: "text-red-500" },
  };

  const cfg = statusConfig[transportState];
  const overlayHealth = useMemo(() => {
    if (!vpOverlay) return null;
    const health =
      vpOverlay.health && typeof vpOverlay.health === "object"
        ? (vpOverlay.health as Record<string, unknown>)
        : {};
    const dataStatus =
      typeof health.data_status === "string" ? health.data_status : null;
    const ocrConfidence =
      typeof health.ocr_confidence === "number" && Number.isFinite(health.ocr_confidence)
        ? Math.round(health.ocr_confidence * 1000) / 1000
        : null;
    const axisStaleMs =
      typeof health.axis_stale_ms === "number" && Number.isFinite(health.axis_stale_ms)
        ? Math.max(0, Math.round(health.axis_stale_ms))
        : null;
    const lastTradeAgeMs =
      typeof health.last_trade_age_ms === "number" && Number.isFinite(health.last_trade_age_ms)
        ? Math.max(0, Math.round(health.last_trade_age_ms))
        : null;
    const updatedAtMs = overlayLastUpdateTs ? Date.parse(overlayLastUpdateTs) : Number.NaN;
    const overlayAgeMs = Number.isFinite(updatedAtMs) ? Math.max(0, Date.now() - updatedAtMs) : null;
    return {
      dataStatus,
      ocrConfidence,
      axisStaleMs,
      lastTradeAgeMs,
      overlayAgeMs,
    };
  }, [overlayLastUpdateTs, vpOverlay]);
  const { symbol: selectedSymbol, exchange: selectedExchange } = useMemo(
    () => parseSelectedAsset(selectedTicker),
    [selectedTicker],
  );
  const normalizedSelectedSymbol = useMemo(
    () => normalizeTickerSymbol(selectedSymbol),
    [selectedSymbol],
  );
  const normalizedStreamingTicker = useMemo(
    () => normalizeTickerSymbol(streamingTicker),
    [streamingTicker],
  );

  const marketUpdateIndicator = useMemo(() => {
    if (assetSwitchStatus === "switching") {
      return {
        label: "ATUALIZANDO ATIVO...",
        color: "text-amber-300",
        detail: "Troca de ativo em andamento.",
      };
    }
    if (transportState === "disconnected") {
      return {
        label: "SEM ATUALIZAÇÃO: CONEXÃO",
        color: "text-red-400",
        detail:
          probe.lastError != null
            ? `Distributor inacessível. Último erro: ${probe.lastError}`
            : "Sem conexão com o distributor.",
      };
    }
    if (transportState === "initializing") {
      return {
        label: "INICIALIZANDO DISTRIBUTOR",
        color: "text-amber-300",
        detail: probe.ipcStatus
          ? `Pipeline em inicialização (${probe.ipcStatus}).`
          : "Distributor online, aguardando prontidão do feed.",
      };
    }
    if (transportState === "awaiting_feed") {
      const wsHint =
        probe.wsClients != null
          ? `WS clientes: ${probe.wsClients}.`
          : wsStatus === "connected"
            ? "WS conectado."
            : "WS reconectando.";
      return {
        label: "SEM ATUALIZAÇÃO: AGUARDANDO FEED",
        color: "text-amber-300",
        detail: `${wsHint} Aguardando novo evento de mercado.`,
      };
    }
    if (timesTradesLoading) {
      return {
        label: "ATUALIZANDO TIMES & TRADES...",
        color: "text-amber-300",
        detail: timesTradesLoadingMessage || "Aguardando primeiro trade do ativo.",
      };
    }
    if (!Number.isFinite(latestMarketEventMs)) {
      return {
        label: "SEM ATUALIZAÇÃO: AGUARDANDO FEED",
        color: "text-amber-300",
        detail: "Feed pronto, mas sem evento recente para o ativo atual.",
      };
    }
    const ageMs = Math.max(0, nowMs - latestMarketEventMs);
    const ageSec = Math.floor(ageMs / 1000);
    if (ageMs <= STALE_ASSET_MS) {
      return {
        label: `ATIVO OK (${ageSec}s)`,
        color: "text-emerald-400",
        detail: `Última atualização há ${ageSec}s.`,
      };
    }
    if (
      normalizedStreamingTicker &&
      normalizedSelectedSymbol &&
      normalizedStreamingTicker !== normalizedSelectedSymbol
    ) {
      return {
        label: "SEM ATUALIZAÇÃO: AGUARDANDO FEED",
        color: "text-amber-300",
        detail: `Stream em ${streamingTicker}, mas ativo selecionado é ${selectedSymbol}.`,
      };
    }
    const hasMatchingStream = Boolean(
      normalizedStreamingTicker &&
        normalizedSelectedSymbol &&
        normalizedStreamingTicker === normalizedSelectedSymbol,
    );
    if (hasMatchingStream) {
      return {
        label: "SEM ATUALIZAÇÃO: AGUARDANDO FEED",
        color: "text-amber-300",
        detail: `${selectedSymbol} sem novos negócios há ${ageSec}s, mas o stream segue ativo para o ativo selecionado.`,
      };
    }
    if (
      ageMs >= OUT_OF_SESSION_MIN_STALE_MS &&
      isLikelyOutOfSession(selectedExchange, new Date(nowMs))
    ) {
      return {
        label: "SEM ATUALIZAÇÃO: AGUARDANDO FEED",
        color: "text-amber-300",
        detail: `${selectedExchange || "Mercado"} fora do pregão. Último dado há ${ageSec}s.`,
      };
    }
    return {
      label: "SEM ATUALIZAÇÃO: AGUARDANDO FEED",
      color: "text-amber-300",
      detail: `${selectedSymbol || "Ativo"} sem atualização há ${ageSec}s.`,
    };
  }, [
    assetSwitchStatus,
    transportState,
    timesTradesLoading,
    timesTradesLoadingMessage,
    latestMarketEventMs,
    nowMs,
    streamingTicker,
    selectedSymbol,
    selectedExchange,
    normalizedSelectedSymbol,
    normalizedStreamingTicker,
    probe.ipcStatus,
    probe.lastError,
    probe.wsClients,
    wsStatus,
  ]);

  return (
    <div className="flex items-center gap-6 px-4 py-2 bg-grid border-b border-border font-mono text-sm">
      <span className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${
          transportState === "connected"
            ? "bg-green-500"
            : transportState === "disconnected"
              ? "bg-red-500"
              : "bg-amber-400"
        }`} />
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
      <span
        className={`text-xs max-w-[320px] truncate ${marketUpdateIndicator.color}`}
        title={marketUpdateIndicator.detail}
      >
        {marketUpdateIndicator.label}
      </span>
      <span className="text-text/80">VWAP: {vwap > 0 ? formatPrice(vwap) : "—"}</span>
      {overlayHealth && (
        <span
          className={`text-xs max-w-[320px] truncate ${
            overlayHealth.dataStatus === "ok"
              ? "text-emerald-400"
              : overlayHealth.dataStatus === "degraded"
                ? "text-amber-300"
                : "text-red-400"
          }`}
          title={[
            `vp_overlay: ${overlayHealth.dataStatus ?? "n/d"}`,
            overlayHealth.ocrConfidence != null ? `ocr ${overlayHealth.ocrConfidence}` : null,
            overlayHealth.axisStaleMs != null ? `axis stale ${overlayHealth.axisStaleMs}ms` : null,
            overlayHealth.lastTradeAgeMs != null ? `trade age ${overlayHealth.lastTradeAgeMs}ms` : null,
            overlayHealth.overlayAgeMs != null ? `publish age ${overlayHealth.overlayAgeMs}ms` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        >
          {overlayHealth.dataStatus ? `VP OVERLAY: ${overlayHealth.dataStatus.toUpperCase()}` : "VP OVERLAY"}
          {overlayHealth.overlayAgeMs != null ? ` (${Math.floor(overlayHealth.overlayAgeMs / 1000)}s)` : ""}
        </span>
      )}
      <span className="text-text/60 ml-auto flex items-center gap-2">
        <button
          type="button"
          id="voice-copilot-open-btn"
          onClick={() => { setCopilotoOpen(true); setAgent007Open(false); }}
          className="px-2 py-1 rounded text-text/70 hover:text-text hover:bg-border/50 text-xs font-mono flex items-center gap-1"
          title="Copiloto 007 — interação por voz"
        >
          <span aria-hidden="true">🎙</span> Copiloto
        </button>
        <button
          type="button"
          onClick={() => { setAgent007Open(true); setCopilotoOpen(false); }}
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

      {copilotoOpen && (
        <div className="fixed inset-0 z-[100] flex justify-end">
          <button
            type="button"
            className="flex-1 bg-black/50 border-0 cursor-default"
            aria-label="Fechar painel"
            onClick={() => setCopilotoOpen(false)}
          />
          <div className="w-full max-w-md h-full bg-grid border-l border-border shadow-xl flex flex-col min-h-0">
            <div className="shrink-0 flex justify-between items-center border-b border-border px-3 py-1">
              <span className="text-xs font-mono text-text/60">Copiloto 007 — Voz</span>
              <button
                type="button"
                onClick={() => setCopilotoOpen(false)}
                className="px-3 py-1 text-xs text-text/60 hover:text-text"
              >
                Fechar
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <VoiceCopilotPanel />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
