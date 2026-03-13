import { create } from "zustand";
import type {
  AlertMessage,
  DailyMessage,
  DomSnapshotMessage,
  TradeMessage,
  WallAddMessage,
  WallRemoveMessage,
} from "../types/messages";

const MAX_ALERTS = 50;
const MAX_AGGR_HISTORY = 50;

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
  setAssetSwitchStatus: (s: AssetSwitchStatus) => void;

  /** Limpa dados de mercado (chamado ao trocar ativo) */
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
  updateTrade: (msg: TradeMessage) => void;

  dailyHigh: number;
  dailyLow: number;
  dailyOpen: number;
  dailyClose: number;
  dailyVolume: number;
  updateDaily: (msg: DailyMessage) => void;
}

export const useMarketStore = create<MarketStore>((set) => ({
  wsStatus: "disconnected",
  setWsStatus: (s) => set({ wsStatus: s }),

  selectedTicker: "WINFUT · BMF",
  setSelectedTicker: (t) => set({ selectedTicker: t }),

  streamingTicker: "",
  assetSwitchStatus: "idle" as AssetSwitchStatus,
  setAssetSwitchStatus: (s) => set({ assetSwitchStatus: s }),

  clearMarketData: () =>
    set({
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
      dailyHigh: 0,
      dailyLow: 0,
      dailyOpen: 0,
      dailyClose: 0,
      dailyVolume: 0,
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
      const wallPriceByOfferId = { ...state.wallPriceByOfferId, [msg.offer_id]: msg.price };
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
  updateTrade: (msg) =>
    set((state) => {
      const net = msg.net_aggression;
      const buyDelta = net > 0 ? net : 0;
      const sellDelta = net < 0 ? -net : 0;

      const agentBuy = { ...state.agentBuyTotals };
      const agentSell = { ...state.agentSellTotals };
      agentBuy[msg.buy_agent] = (agentBuy[msg.buy_agent] ?? 0) + msg.qty;
      agentSell[msg.sell_agent] = (agentSell[msg.sell_agent] ?? 0) + msg.qty;

      const history = [...state.aggrHistory, net].slice(-MAX_AGGR_HISTORY);

      return {
        lastPrice: msg.price,
        vwap: msg.vwap,
        netAggression: net,
        totalBuyAggression: state.totalBuyAggression + buyDelta,
        totalSellAggression: state.totalSellAggression + sellDelta,
        aggrHistory: history,
        agentBuyTotals: agentBuy,
        agentSellTotals: agentSell,
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
}));
