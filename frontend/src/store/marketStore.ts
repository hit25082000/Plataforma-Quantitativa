import { create } from "zustand";
import type {
  Agent007StateMessage,
  AlertMessage,
  BrokerSnapshotMessage,
  DailyMessage,
  DomSnapshotMessage,
  FlowInversionMessage,
  MacdSignalMessage,
  SyncMessage,
  TradeMessage,
  WallAddMessage,
  WallRemoveMessage,
} from "../types/messages";

function isUsableRsi(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function macdMessageHasAnyRsi(m: MacdSignalMessage): boolean {
  return (
    isUsableRsi(m.rsi9) ||
    isUsableRsi(m.rsi18) ||
    isUsableRsi(m.rsi30) ||
    isUsableRsi(m.rsi)
  );
}

/** Evita perder IFR quando uma mensagem parcial chega com rsi9/18/30 null ou ausente. */
function mergeMacdRsiFields(
  prev: MacdSignalMessage | undefined,
  msg: MacdSignalMessage,
): MacdSignalMessage {
  if (prev == null) return msg;
  const out: MacdSignalMessage = { ...msg };
  const keys: (keyof Pick<
    MacdSignalMessage,
    "rsi9" | "rsi18" | "rsi30" | "rsi"
  >)[] = ["rsi9", "rsi18", "rsi30", "rsi"];
  for (const k of keys) {
    if (!isUsableRsi(out[k]) && isUsableRsi(prev[k])) {
      out[k] = prev[k];
    }
  }
  return out;
}

const MAX_ALERTS = 50;
const MAX_FLOW_INVERSIONS = 30;
const MAX_MACD_HISTORY = 50;

/** Passo de agressão para o painel: indicadores e histórico atualizam de 100 em 100 */
export const AGGRESSION_STEP = 100;

export type WsStatus = "connecting" | "connected" | "disconnected";

export type AssetSwitchStatus = "idle" | "switching" | "active" | "error";

/** Série usada para o IFR: Renko 42/16 ou fechamento de candles de 30 min. */
export type IfrSeriesMode = "42r" | "16r" | "30m";

export function ifrSeriesShortLabel(s: IfrSeriesMode): string {
  switch (s) {
    case "30m":
      return "30 min";
    case "16r":
      return "16R";
    default:
      return "42R";
  }
}

/** Calibração do gráfico na janela secundária do overlay (sincronizada por eventos Tauri). */
export interface OverlayCalibrationState {
  pricePerPixel: number;
  originPrice: number;
  originY: number;
  chartX: number;
  chartY: number;
  chartWidth: number;
  chartHeight: number;
  updatedAt: string;
}

export interface DomLevel {
  price: number;
  qty: number;
  count: number;
}

interface MarketStore {
  wsStatus: WsStatus;
  setWsStatus: (s: WsStatus) => void;

  /** Ticker selecionado pelo usuário na UI (fonte de verdade para troca de ativo) */
  selectedTicker: string;
  setSelectedTicker: (t: string) => void;

  /** Série do IFR no distributor (Renko ou 30 min) */
  ifrSeries: IfrSeriesMode;
  setIfrSeries: (s: IfrSeriesMode) => void;

  /** Ticker recebido do stream (para verificação/debug) */
  streamingTicker: string;

  assetSwitchStatus: AssetSwitchStatus;
  assetSwitchMessage: string;
  setAssetSwitchStatus: (s: AssetSwitchStatus, message?: string) => void;

  /** Limpa alertas e todos os dados de mercado ao trocar de ativo */
  clearMarketData: () => void;

  /**
   * Última `trade_date` recebida em daily (engine). `null` até o primeiro daily com data.
   * Troca de dia dispara zeragem só dos totais de corretora (saldo).
   */
  lastDailyTradeDate: string | null;

  alerts: AlertMessage[];
  addAlert: (a: AlertMessage) => void;

  domBuy: DomLevel[];
  domSell: DomLevel[];
  activeWalls: Set<number>;
  wallPriceByOfferId: Record<number, number>;
  updateDom: (msg: DomSnapshotMessage) => void;
  addWall: (msg: WallAddMessage) => void;
  removeWall: (msg: WallRemoveMessage) => void;

  lastPrice: number;
  vwap: number;
  agentBuyTotals: Record<number, number>;
  agentSellTotals: Record<number, number>;
  /** Σ (preço × qty) em trades onde o agente é agressor comprador */
  agentBuyFinancial: Record<number, number>;
  /** Σ (preço × qty) em trades onde o agente é agressor vendedor */
  agentSellFinancial: Record<number, number>;
  agentNames: Record<number, string>;
  agentShortNames: Record<number, string>;
  updateTrade: (msg: TradeMessage) => void;
  updateTradeBatch: (msgs: TradeMessage[]) => void;
  applyBrokerSnapshot: (msg: BrokerSnapshotMessage) => void;

  dailyHigh: number;
  dailyLow: number;
  dailyOpen: number;
  dailyClose: number;
  dailyVolume: number;
  updateDaily: (msg: DailyMessage) => void;

  inSync: boolean;
  syncVariations: Record<string, number>;
  updateSync: (msg: SyncMessage) => void;

  flowInversions: FlowInversionMessage[];
  addFlowInversion: (msg: FlowInversionMessage) => void;

  macdHistory: MacdSignalMessage[];
  macdDirection: "buy" | "sell" | null;
  updateMacd: (msg: MacdSignalMessage) => void;

  /** Estado exclusivo da webview do overlay (pode ser atualizado pela janela principal via eventos). */
  overlayCalibration: OverlayCalibrationState | null;
  overlayUbsPrice: number | null;
  overlayAvgPrice: number | null;
  overlayLastUpdateTs: string | null;

  agent007: Agent007StateMessage | null;
  setAgent007State: (s: Agent007StateMessage) => void;
}

export const useMarketStore = create<MarketStore>((set) => ({
  wsStatus: "disconnected",
  setWsStatus: (s) => set({ wsStatus: s }),

  selectedTicker: "WINFUT · BMF",
  setSelectedTicker: (t) => set({ selectedTicker: t }),

  ifrSeries: "42r",
  setIfrSeries: (s) => set({ ifrSeries: s }),

  streamingTicker: "",
  assetSwitchStatus: "idle" as AssetSwitchStatus,
  assetSwitchMessage: "",
  setAssetSwitchStatus: (s, message) =>
    set({
      assetSwitchStatus: s,
      assetSwitchMessage: s === "error" && message ? message : "",
    }),

  /** Limpa alertas, DOM, trades, daily, sync, flow inversions e MACD ao trocar de ativo */
  clearMarketData: () =>
    set({
      alerts: [],
      domBuy: [],
      domSell: [],
      activeWalls: new Set<number>(),
      wallPriceByOfferId: {},
      lastPrice: 0,
      vwap: 0,
      agentBuyTotals: {},
      agentSellTotals: {},
      agentBuyFinancial: {},
      agentSellFinancial: {},
      agentNames: {},
      agentShortNames: {},
      lastDailyTradeDate: null,
      dailyHigh: 0,
      dailyLow: 0,
      dailyOpen: 0,
      dailyClose: 0,
      dailyVolume: 0,
      inSync: true,
      syncVariations: {},
      flowInversions: [],
      macdHistory: [],
      macdDirection: null,
      streamingTicker: "",
    }),

  alerts: [],
  addAlert: (a) =>
    set((state) => ({
      alerts: [a, ...state.alerts].slice(0, MAX_ALERTS),
    })),

  domBuy: [],
  domSell: [],
  activeWalls: new Set<number>(),
  wallPriceByOfferId: {},
  updateDom: (msg) =>
    set({
      domBuy: msg.buy,
      domSell: msg.sell,
      streamingTicker: msg.ticker,
    }),
  addWall: (msg) =>
    set((state) => {
      const next = new Set(state.activeWalls);
      next.add(msg.offer_id);
      const wallPriceByOfferId = {
        ...state.wallPriceByOfferId,
        [msg.offer_id]: msg.price,
      };
      return { activeWalls: next, wallPriceByOfferId };
    }),
  removeWall: (msg) =>
    set((state) => {
      const next = new Set(state.activeWalls);
      next.delete(msg.offer_id);
      const wallPriceByOfferId = { ...state.wallPriceByOfferId };
      delete wallPriceByOfferId[msg.offer_id];
      return { activeWalls: next, wallPriceByOfferId };
    }),

  lastPrice: 0,
  vwap: 0,
  agentBuyTotals: {},
  agentSellTotals: {},
  agentBuyFinancial: {},
  agentSellFinancial: {},
  agentNames: {},
  agentShortNames: {},
  lastDailyTradeDate: null,
  updateTrade: (msg) =>
    set((state) => {
      const agentNames = { ...state.agentNames };
      if (msg.buy_agent_name != null)
        agentNames[msg.buy_agent] = msg.buy_agent_name;
      if (msg.sell_agent_name != null)
        agentNames[msg.sell_agent] = msg.sell_agent_name;

      const agentShortNames = { ...state.agentShortNames };
      if (msg.buy_agent_short_name != null)
        agentShortNames[msg.buy_agent] = msg.buy_agent_short_name;
      if (msg.sell_agent_short_name != null)
        agentShortNames[msg.sell_agent] = msg.sell_agent_short_name;

      return {
        lastPrice: msg.price,
        vwap: msg.vwap,
        agentNames,
        agentShortNames,
        streamingTicker: msg.ticker,
      };
    }),
  updateTradeBatch: (msgs) =>
    set((state) => {
      if (msgs.length === 0) return {};
      const agentNames = { ...state.agentNames };
      const agentShortNames = { ...state.agentShortNames };

      let lastPrice = state.lastPrice;
      let vwap = state.vwap;
      let streamingTicker = state.streamingTicker;

      for (const msg of msgs) {
        if (msg.buy_agent_name != null) agentNames[msg.buy_agent] = msg.buy_agent_name;
        if (msg.sell_agent_name != null) agentNames[msg.sell_agent] = msg.sell_agent_name;
        if (msg.buy_agent_short_name != null)
          agentShortNames[msg.buy_agent] = msg.buy_agent_short_name;
        if (msg.sell_agent_short_name != null)
          agentShortNames[msg.sell_agent] = msg.sell_agent_short_name;
        lastPrice = msg.price;
        vwap = msg.vwap;
        streamingTicker = msg.ticker;
      }

      return {
        lastPrice,
        vwap,
        agentNames,
        agentShortNames,
        streamingTicker,
      };
    }),
  applyBrokerSnapshot: (msg) =>
    set(() => {
      const toNumberRecord = (
        src: Record<string, number> | undefined,
      ): Record<number, number> => {
        const out: Record<number, number> = {};
        if (!src) return out;
        for (const [k, v] of Object.entries(src)) {
          const id = Number(k);
          if (Number.isFinite(id) && Number.isFinite(v)) out[id] = Number(v);
        }
        return out;
      };
      const toStringRecord = (
        src: Record<string, string> | undefined,
      ): Record<number, string> => {
        const out: Record<number, string> = {};
        if (!src) return out;
        for (const [k, v] of Object.entries(src)) {
          const id = Number(k);
          if (Number.isFinite(id) && typeof v === "string" && v.trim()) out[id] = v;
        }
        return out;
      };
      const td = msg.trade_date?.trim();
      return {
        agentBuyTotals: toNumberRecord(msg.buy_qty),
        agentSellTotals: toNumberRecord(msg.sell_qty),
        agentBuyFinancial: toNumberRecord(msg.buy_fin),
        agentSellFinancial: toNumberRecord(msg.sell_fin),
        agentNames: toStringRecord(msg.agent_name),
        agentShortNames: toStringRecord(msg.agent_short_name),
        lastDailyTradeDate: td ? td : null,
      };
    }),

  dailyHigh: 0,
  dailyLow: 0,
  dailyOpen: 0,
  dailyClose: 0,
  dailyVolume: 0,
  updateDaily: (msg) =>
    set((state) => {
      const td = msg.trade_date?.trim();
      const base = {
        dailyHigh: msg.high,
        dailyLow: msg.low,
        dailyOpen: msg.open,
        dailyClose: msg.close,
        dailyVolume: msg.volume,
        streamingTicker: msg.ticker,
      };
      if (!td) return base;
      const prev = state.lastDailyTradeDate;
      if (prev != null && prev !== td) {
        return {
          ...base,
          agentBuyTotals: {},
          agentSellTotals: {},
          agentBuyFinancial: {},
          agentSellFinancial: {},
          agentNames: {},
          agentShortNames: {},
          lastDailyTradeDate: td,
        };
      }
      return { ...base, lastDailyTradeDate: td };
    }),

  inSync: true,
  syncVariations: {},
  updateSync: (msg) =>
    set((state) => {
      const variations =
        msg.variations &&
        typeof msg.variations === "object" &&
        Object.keys(msg.variations).length > 0
          ? msg.variations
          : state.syncVariations;
      return { inSync: msg.in_sync, syncVariations: variations };
    }),

  flowInversions: [],
  addFlowInversion: (m) =>
    set((state) => ({
      flowInversions: [m, ...state.flowInversions].slice(
        0,
        MAX_FLOW_INVERSIONS,
      ),
    })),

  macdHistory: [],
  macdDirection: null,
  updateMacd: (msg) =>
    set((state) => {
      const last = state.macdHistory[state.macdHistory.length - 1];
      const mergeFromLast =
        last != null &&
        (msg.partial === true ||
          (last.partial === true && !macdMessageHasAnyRsi(msg)));
      const merged = mergeFromLast ? mergeMacdRsiFields(last, msg) : msg;
      let nextHistory = state.macdHistory;
      if (msg.partial) {
        nextHistory = last?.partial
          ? [...state.macdHistory.slice(0, -1), merged]
          : [...state.macdHistory, merged];
      } else {
        nextHistory = last?.partial
          ? [...state.macdHistory.slice(0, -1), merged]
          : [...state.macdHistory, merged];
      }
      return {
        macdHistory: nextHistory.slice(-MAX_MACD_HISTORY),
        macdDirection: merged.direction,
      };
    }),

  overlayCalibration: null,
  overlayUbsPrice: null,
  overlayAvgPrice: null,
  overlayLastUpdateTs: null,

  agent007: null,
  setAgent007State: (s) => set({ agent007: s }),
}));

type MarketState = ReturnType<typeof useMarketStore.getState>;

/** Fonte do preço médio usado para inicialização de posições do overlay OCR. */
export const selectOverlayAveragePrice = (state: MarketState): number =>
  state.vwap;
