import type {
  TapeIntelligenceLevel,
  TapeIntelligenceMessage,
  TopPlayerAvgLine,
  VolumeProfileLevel,
  VolumeProfileMessage,
  VpOverlayMessage,
} from "../types/messages";

function inferPriceStep(levels: VolumeProfileLevel[]): number {
  const prices = [...new Set(levels.map((l) => l.price))].filter((p) => Number.isFinite(p)).sort((a, b) => a - b);
  if (prices.length < 2) return 5;
  let min = Infinity;
  for (let i = 1; i < prices.length; i++) {
    const d = Math.abs(prices[i] - prices[i - 1]);
    if (d > 0 && d < min) min = d;
  }
  return Number.isFinite(min) && min > 0 ? min : 5;
}

function rowVol(holder: VpOverlayMessage["poc"]["holder"]): number {
  const c = Number(holder?.contracts);
  return Number.isFinite(c) && c > 0 ? Math.round(c) : 0;
}

function mkTop3Row(
  playerId: number,
  price: number,
  vol: number,
  buyAbs: number,
  sellAbs: number,
): TapeIntelligenceLevel {
  return {
    player: playerId,
    price,
    total_vol: vol,
    bid_vol: 0,
    ask_vol: 0,
    buy_absorption: buyAbs,
    sell_absorption: sellAbs,
  };
}

export function vpOverlayToVolumeProfile(msg: VpOverlayMessage): VolumeProfileMessage {
  const raw = Array.isArray(msg.levels) ? msg.levels : [];
  const levels: VolumeProfileLevel[] = raw
    .map((row) => {
      const yRaw = (row as { y?: unknown }).y;
      const y =
        typeof yRaw === "number" && Number.isFinite(yRaw) ? yRaw : undefined;
      const base: VolumeProfileLevel = {
        price: Number(row.price),
        total_vol: Number(row.total_vol) || 0,
        bid_vol: Number(row.bid_vol) || 0,
        ask_vol: Number(row.ask_vol) || 0,
        pct_of_max: Number(row.pct_of_max) || 0,
      };
      if (y !== undefined) base.y = y;
      return base;
    })
    .filter((row) => Number.isFinite(row.price));
  const total_vol = levels.reduce((a, x) => a + x.total_vol, 0);
  const scope = String(msg.scope || "session").toLowerCase();
  const period: VolumeProfileMessage["period"] =
    scope === "week" ? "week" : scope === "manual" ? "manual" : "day";
  const tsMs = msg.updated_at < 1e12 ? Math.round(msg.updated_at * 1000) : Math.round(msg.updated_at);
  const out: VolumeProfileMessage = {
    topic: "market",
    type: "volume_profile",
    ticker: msg.symbol,
    period,
    timestamp: tsMs,
    price_step: inferPriceStep(levels),
    total_vol,
    poc: msg.poc.price,
    vah: msg.vah.price,
    val: msg.val.price,
    levels,
  };
  const py = msg.poc?.y;
  const vy = msg.val?.y;
  const hy = msg.vah?.y;
  if (typeof py === "number" && Number.isFinite(py)) out.poc_y = py;
  if (typeof vy === "number" && Number.isFinite(vy)) out.val_y = vy;
  if (typeof hy === "number" && Number.isFinite(hy)) out.vah_y = hy;
  if (msg.demo === true) {
    (out as VolumeProfileMessage & { demo?: boolean }).demo = true;
  }
  return out;
}

export function vpOverlayToTapeIntelligence(msg: VpOverlayMessage): TapeIntelligenceMessage {
  const pocId = Number(msg.poc.player_id) || 0;
  const valId = Number(msg.val.player_id) || 0;
  const vahId = Number(msg.vah.player_id) || 0;
  const pocV = rowVol(msg.poc.holder);
  const valV = rowVol(msg.val.holder);
  const vahV = rowVol(msg.vah.holder);
  const topAvgRaw = msg.top_player_avg_lines;
  const top_player_avg_lines: TopPlayerAvgLine[] = Array.isArray(topAvgRaw)
    ? topAvgRaw.filter((x): x is Record<string, unknown> => x != null && typeof x === "object").map((x) => ({
        player_id: Number(x.player_id) || 0,
        player_name: typeof x.player_name === "string" ? x.player_name : undefined,
        mode: (x.mode === "buy" || x.mode === "sell" || x.mode === "net" ? x.mode : "total") as TopPlayerAvgLine["mode"],
        avg_price: Number(x.avg_price) || 0,
        label: String(x.label ?? ""),
        dashed: Boolean(x.dashed),
      }))
    : [];
  const tsMs = msg.updated_at < 1e12 ? Math.round(msg.updated_at * 1000) : Math.round(msg.updated_at);
  const out: TapeIntelligenceMessage = {
    topic: "market",
    type: "tape_intelligence",
    ticker: msg.symbol,
    timestamp: tsMs,
    poc_price: msg.poc.price,
    vah_price: msg.vah.price,
    val_price: msg.val.price,
    poc_player: pocId,
    val_buyer: valId,
    vah_seller: vahId,
    poc_top3:
      pocId > 0 ? [mkTop3Row(pocId, msg.poc.price, pocV || 1, 0, 0)] : [],
    val_top3:
      valId > 0
        ? [mkTop3Row(valId, msg.val.price, valV || 1, Number(msg.val.holder.contracts) || 0, 0)]
        : [],
    vah_top3:
      vahId > 0
        ? [mkTop3Row(vahId, msg.vah.price, vahV || 1, 0, Number(msg.vah.holder.contracts) || 0)]
        : [],
    top_player_avg_lines,
    val_holder_state: msg.val.holder.state,
    vah_holder_state: msg.vah.holder.state,
  };
  const tpy = msg.poc?.y;
  const tvy = msg.val?.y;
  const thy = msg.vah?.y;
  if (typeof tpy === "number" && Number.isFinite(tpy)) out.poc_y = tpy;
  if (typeof tvy === "number" && Number.isFinite(tvy)) out.val_y = tvy;
  if (typeof thy === "number" && Number.isFinite(thy)) out.vah_y = thy;
  if (msg.demo === true) {
    (out as TapeIntelligenceMessage & { demo?: boolean }).demo = true;
  }
  return out;
}
