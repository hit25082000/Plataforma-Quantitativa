import { create } from "zustand";
import type {
  AlertMessage,
  DailyMessage,
  DomSnapshotMessage,
  FlowInversionMessage,
  MacdSignalMessage,
  SyncMessage,
  TradeMessage,
  WallAddMessage,
  WallRemoveMessage,
} from "../types/messages";

const MAX_ALERTS = 50;
const MAX_AGGR_HISTORY = 50;
const MAX_FLOW_INVERSIONS = 30;
const MAX_MACD_HISTORY = 50;
const MAX_PRICE_CLOSES = 50;

/** Passo de agressão para o painel: indicadores e histórico atualizam de 100 em 100 */
export const AGGRESSION_STEP = 100;

export type WsStatus = "connecting" | "connected" | "disconnected";

export type AssetSwitchStatus = "idle" | "switching" | "active" | "error";

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

  /** Ticker recebido do stream (para verificação/debug) */
  streamingTicker: string;

  assetSwitchStatus: AssetSwitchStatus;
  assetSwitchMessage: string;
  setAssetSwitchStatus: (s: AssetSwitchStatus, message?: string) => void;

  /** Limpa alertas e todos os dados de mercado ao trocar de ativo */
  clearMarketData: () => void;

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
  netAggression: number;
  totalBuyAggression: number;
  totalSellAggression: number;
  aggrHistory: number[];
  agentBuyTotals: Record<number, number>;
  agentSellTotals: Record<number, number>;
  agentNames: Record<number, string>;
  agentShortNames: Record<number, string>;
  updateTrade: (msg: TradeMessage) => void;

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

  /** Últimos preços (close) por trade, para fallback de IFR quando não há macd_signal */
  priceCloses: number[];
}

export const useMarketStore = create<MarketStore>((set) => ({
  wsStatus: "disconnected",
  setWsStatus: (s) => set({ wsStatus: s }),

  selectedTicker: "WINFUT · BMF",
  setSelectedTicker: (t) => set({ selectedTicker: t }),

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
      netAggression: 0,
      totalBuyAggression: 0,
      totalSellAggression: 0,
      aggrHistory: [],
      agentBuyTotals: {},
      agentSellTotals: {},
      agentNames: {},
      agentShortNames: {},
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
      priceCloses: [],
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
  netAggression: 0,
  totalBuyAggression: 0,
  totalSellAggression: 0,
  aggrHistory: [],
  agentBuyTotals: {},
  agentSellTotals: {},
  agentNames: {},
  agentShortNames: {},
  updateTrade: (msg) =>
    set((state) => {
      const net = msg.net_aggression;
      const buyDelta = net > 0 ? net : 0;
      const sellDelta = net < 0 ? -net : 0;

      const agentBuy = { ...state.agentBuyTotals };
      const agentSell = { ...state.agentSellTotals };
      agentBuy[msg.buy_agent] = (agentBuy[msg.buy_agent] ?? 0) + msg.qty;
      agentSell[msg.sell_agent] = (agentSell[msg.sell_agent] ?? 0) + msg.qty;

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

      const cumulativeNet =
        state.totalBuyAggression +
        buyDelta -
        (state.totalSellAggression + sellDelta);
      const last =
        state.aggrHistory.length > 0
          ? state.aggrHistory[state.aggrHistory.length - 1]
          : null;
      const shouldAppendHistory =
        last === null ||
        Math.abs(cumulativeNet - last) >= AGGRESSION_STEP;
      const history = shouldAppendHistory
        ? [...state.aggrHistory, cumulativeNet].slice(-MAX_AGGR_HISTORY)
        : state.aggrHistory;

      const priceCloses = [...(state.priceCloses ?? []), msg.price].slice(
        -MAX_PRICE_CLOSES,
      );
      return {
        lastPrice: msg.price,
        vwap: msg.vwap,
        netAggression: net,
        totalBuyAggression: state.totalBuyAggression + buyDelta,
        totalSellAggression: state.totalSellAggression + sellDelta,
        aggrHistory: history,
        agentBuyTotals: agentBuy,
        agentSellTotals: agentSell,
        agentNames,
        agentShortNames,
        priceCloses,
        streamingTicker: msg.ticker,
      };
    }),

  dailyHigh: 0,
  dailyLow: 0,
  dailyOpen: 0,
  dailyClose: 0,
  dailyVolume: 0,
  updateDaily: (msg) =>
    set({
      dailyHigh: msg.high,
      dailyLow: msg.low,
      dailyOpen: msg.open,
      dailyClose: msg.close,
      dailyVolume: msg.volume,
      streamingTicker: msg.ticker,
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
  priceCloses: [],
  updateMacd: (msg) =>
    set((state) => ({
      macdHistory: [...state.macdHistory, msg].slice(-MAX_MACD_HISTORY),
      macdDirection: msg.direction,
    })),
}));
