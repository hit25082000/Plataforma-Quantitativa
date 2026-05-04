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

export interface VolumeProfileLevel {
  price: number;
  total_vol: number;
  bid_vol: number;
  ask_vol: number;
  pct_of_max: number;
  /** Y em px (tela) quando o distributor enriquece com eixo OCR */
  y?: number;
}

export interface VolumeProfileMessage {
  topic: "market";
  type: "volume_profile";
  ticker: string;
  period: "day" | "week" | "manual";
  timestamp: number;
  price_step: number;
  total_vol: number;
  poc: number;
  vah: number;
  val: number;
  levels: VolumeProfileLevel[];
  poc_y?: number;
  vah_y?: number;
  val_y?: number;
}

export interface TopPlayerAvgLine {
  player_id: number;
  player_name?: string;
  mode: "total" | "buy" | "sell" | "net";
  avg_price: number;
  label: string;
  dashed?: boolean;
}

export interface TapeIntelligenceLevel {
  player: number;
  player_id?: number;
  player_name?: string;
  price: number;
  total_vol: number;
  bid_vol: number;
  ask_vol: number;
  buy_absorption?: number;
  sell_absorption?: number;
}

export interface TapeIntelligenceMessage {
  topic: "market";
  type: "tape_intelligence";
  ticker: string;
  timestamp: number;
  poc_price: number;
  vah_price: number;
  val_price: number;
  poc_player: number;
  val_buyer: number;
  vah_seller: number;
  poc_player_name?: string;
  val_buyer_name?: string;
  vah_seller_name?: string;
  poc_top3: TapeIntelligenceLevel[];
  vah_top3: TapeIntelligenceLevel[];
  val_top3: TapeIntelligenceLevel[];
  poc_y?: number;
  vah_y?: number;
  val_y?: number;
  val_holder_state?: string;
  vah_holder_state?: string;
  top_player_avg_lines?: TopPlayerAvgLine[];
}

export interface VpOverlayHolder {
  method: string;
  state: string;
  contracts: number;
  participation_pct: number;
}

export interface VpOverlayAnchor {
  price: number;
  player_id: number;
  label: string;
  holder: VpOverlayHolder;
  line_color?: string;
  y?: number;
}

export interface VpOverlayDisplay {
  overlay_enabled?: boolean;
  poc_visible?: boolean;
  val_vah_visible?: boolean;
  labels_visible?: boolean;
  histogram_visible?: boolean;
  top_avg_visible?: boolean;
  stretch_lines?: boolean;
  max_avg_lines?: number;
  max_histogram_width_px?: number;
  max_visible_histogram_levels?: number;
}

export interface VpOverlayMessage {
  topic: "market";
  type: "vp_overlay";
  version: number;
  symbol: string;
  raw_ticker?: string;
  scope: string;
  sequence: number;
  updated_at: number;
  poc: VpOverlayAnchor;
  val: VpOverlayAnchor;
  vah: VpOverlayAnchor;
  levels: VolumeProfileLevel[];
  top_player_avg_lines: unknown[];
  display: VpOverlayDisplay;
  health: Record<string, unknown>;
  axis?: Record<string, unknown>;
  demo?: boolean;
}

export interface OverlayDebugVisualAxisLabel {
  value: number;
  y_screen: number;
}

export interface OverlayDebugVisualRegression {
  slope?: number;
  intercept?: number;
  value_per_px?: number;
}

export interface OverlayDebugVisualRect {
  left?: number;
  top?: number;
  width?: number;
  height?: number;
}

export interface OverlayDebugVisualPayload {
  ocr_labels?: OverlayDebugVisualAxisLabel[];
  regression?: OverlayDebugVisualRegression;
  analysis_roi?: OverlayDebugVisualRect;
  chart_bounds?: OverlayDebugVisualRect;
  axis_samples?: Array<{
    value: number;
    y_capture?: number;
    y_screen: number;
    y_chart?: number;
    y_predicted?: number;
    error_px?: number;
  }>;
  axis_fit_canonical?: Record<string, unknown>;
}

export interface VpOverlayHealthDebug {
  data_status?: string;
  axis_stale_ms?: number;
  last_trade_age_ms?: number;
  last_overlay_publish_age_ms?: number;
  last_overlay_publish_age_sec?: number;
  overlay_age_state?: "fresh" | "stale" | "missing";
  ocr_confidence?: number;
  axis_status?: string;
  axis_source?: string;
  bad_frames?: number;
  pending_frames?: number;
  labels_count?: number;
  residual_px?: number;
  max_error_px?: number;
  slope?: number;
  intercept?: number;
  value_per_px?: number;
}

export interface VpOverlayDebugMessage extends VpOverlayMessage {
  health: VpOverlayMessage["health"] & VpOverlayHealthDebug;
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

export interface IpcFallbackMessage {
  topic: "system";
  type: "ipc_fallback";
  requested_mode: "shm" | "zmq";
  effective_mode: "websocket" | "shm" | "zmq";
  reason: string;
  mapping_name?: string;
  ts?: string;
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
  | VolumeProfileMessage
  | TapeIntelligenceMessage
  | VpOverlayMessage
  | Agent007StateMessage
  | IpcFallbackMessage;

/** Vários payloads em um único frame WS (distributor → UI). */
export interface WsBatchMessage {
  topic: "ws_batch";
  items: WsSingleMessage[];
}

export type WsMessage = WsSingleMessage | WsBatchMessage;
