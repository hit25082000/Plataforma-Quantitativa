export interface AlertMessage {
  topic: "alert";
  rule: 1 | 2 | 3 | 5 | 6;
  ticker: string;
  direction: "buy" | "sell" | "neutral";
  conviction: "low" | "medium" | "high";
  label: string;
  price: number;
  data: Record<string, unknown>;
  ts: string;
}

export interface TradeMessage {
  topic: "market";
  type: "trade";
  ticker: string;
  price: number;
  qty: number;
  buy_agent: number;
  sell_agent: number;
  trade_type: number;
  trade_number?: number;
  trade_date?: string;
  trade_source?: "history" | "realtime";
  is_edit?: boolean;
  vwap: number;
  net_aggression: number;
  ts: string;
  buy_agent_name?: string;
  sell_agent_name?: string;
  buy_agent_short_name?: string;
  sell_agent_short_name?: string;
}

export interface DomLevel {
  price: number;
  qty: number;
  count: number;
}

export interface DomSnapshotMessage {
  topic: "market";
  type: "dom_snapshot";
  ticker: string;
  buy: DomLevel[];
  sell: DomLevel[];
  ts: string;
}

export interface WallAddMessage {
  topic: "market";
  type: "wall_add";
  ticker: string;
  price: number;
  qty: number;
  side: number;
  offer_id: number;
  agent_id: number;
  ts: string;
}

export interface WallRemoveMessage {
  topic: "market";
  type: "wall_remove";
  ticker: string;
  offer_id: number;
  elapsed_ms: number;
  was_traded: boolean;
  ts: string;
}

export interface DailyMessage {
  topic: "market";
  type: "daily";
  ticker: string;
  high: number;
  low: number;
  open: number;
  close: number;
  volume: number;
  ts: string;
  /** Data do pregão (ex.: vinda da DLL); usada para zerar saldo por corretora ao mudar o dia. */
  trade_date?: string;
}

export interface BrokerSnapshotMessage {
  topic: "market";
  type: "broker_snapshot";
  trade_date?: string | null;
  buy_qty: Record<string, number>;
  sell_qty: Record<string, number>;
  buy_fin: Record<string, number>;
  sell_fin: Record<string, number>;
  agent_name: Record<string, string>;
  agent_short_name: Record<string, string>;
  ts: string;
}

export interface SyncMessage {
  topic: "sync";
  in_sync: boolean;
  variations: Record<string, number>;
  ts: string;
}

export interface FlowInversionMessage {
  topic: "market";
  type: "flow_inversion";
  agent_name: string;
  previous_delta: number;
  current_delta: number;
  ts: string;
}

export interface MacdSignalMessage {
  topic: "market";
  type: "macd_signal";
  value: number;
  signal_line: number;
  histogram: number;
  direction: "buy" | "sell";
  candle_close: number;
  ts: string;
  rsi?: number;
  rsi9?: number;
  rsi18?: number;
  rsi30?: number;
  /** Tijolo Renko (pontos) usado no cálculo do IFR desta mensagem; ausente em modo 30m */
  renko_brick_points?: number | null;
  /** Série do IFR: renko 42r/16r ou candle 30m */
  ifr_series?: string;
  partial?: boolean;
}

export type Agent007Signal = "green" | "red" | "neutral";

export type Agent007WeisSide = "buy" | "sell" | "unknown";

export type Agent007PriceVsVwap = "above" | "below" | "at";

export interface Agent007Alert {
  kind: string;
  text: string;
  ts: string;
}

export interface Agent007InversionBrief {
  agent_name?: string;
  previous_delta?: number;
  current_delta?: number;
  ts?: string;
}

export interface Agent007StateMessage {
  topic: "agent007";
  type: "state";
  ticker: string;
  last_price: number;
  vwap: number;
  urgency_0_100: number;
  signal: Agent007Signal;
  weis_side: Agent007WeisSide;
  weis_mode: string;
  price_vs_vwap: Agent007PriceVsVwap;
  entry_buy_valid: boolean;
  entry_filter_reason: string | null;
  recent_inversions: Agent007InversionBrief[];
  alerts: Agent007Alert[];
  ts: string;
}

export interface OverlayAxisDeltaInterval {
  i: number;
  value_delta: number;
  y_delta: number;
  value_per_px_segment: number;
}

export interface OverlayAxisDeltas {
  delta_first_last_value: number;
  delta_first_last_y: number;
  delta_intervals: OverlayAxisDeltaInterval[];
  labels_count: number;
}

export type WsSingleMessage =
  | AlertMessage
  | TradeMessage
  | BrokerSnapshotMessage
  | DomSnapshotMessage
  | WallAddMessage
  | WallRemoveMessage
  | DailyMessage
  | SyncMessage
  | FlowInversionMessage
  | MacdSignalMessage
  | Agent007StateMessage;

/** Vários payloads em um único frame WS (distributor → UI). */
export interface WsBatchMessage {
  topic: "ws_batch";
  items: WsSingleMessage[];
}

export type WsMessage = WsSingleMessage | WsBatchMessage;
