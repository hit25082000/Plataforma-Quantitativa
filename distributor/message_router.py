"""Message routing with JSON validation and dom_snapshot throttling."""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any, Optional

from agent_007 import Agent007Engine
from candle_macd import CandleMacd
from config import (
    BROKER_SNAPSHOT_EVERY_MS,
    ROUTER_METRICS_LOG_EVERY_MS,
    UI_SNAPSHOT_INTERVAL_MS,
    UI_TRADE_BATCH_MAX_ITEMS,
)
from flow_tracker import FlowTracker
from stats_logger import StatsLogger
from vp_ocr_enrich import enrich_vp_overlay_payload, enrich_vp_ti_message
from vp_overlay_consolidator import VpOverlayConsolidator

if TYPE_CHECKING:
    from connection_manager import ConnectionManager
    from realtime_rag import RealtimeRagEngine

logger = logging.getLogger(__name__)

WIN_CONTRACT_RE = re.compile(r"^WIN[A-Z]\d{2}$", re.IGNORECASE)
IND_CONTRACT_RE = re.compile(r"^IND[A-Z]\d{2}$", re.IGNORECASE)


def canonical_symbol(raw_symbol: str) -> str:
    s = (raw_symbol or "").strip().upper()
    if not s:
        return ""
    if s in {"WINFUT", "WIN"} or WIN_CONTRACT_RE.match(s):
        return "WINFUT"
    if s in {"INDFUT", "IND"} or IND_CONTRACT_RE.match(s):
        return "INDFUT"
    return s


class MessageRouter:
    """Routes messages from ZMQ to WebSocket clients with validation and throttle."""

    def __init__(
        self,
        manager: "ConnectionManager",
        throttle_ms: int,
        agent007: Optional[Agent007Engine] = None,
        rag_engine: Optional["RealtimeRagEngine"] = None,
        vp_tape_manager: Optional["ConnectionManager"] = None,
        vp_overlay_manager: Optional["ConnectionManager"] = None,
        vp_overlay_consolidator: Optional[VpOverlayConsolidator] = None,
        ui_snapshot_interval_ms: int = UI_SNAPSHOT_INTERVAL_MS,
        ui_trade_batch_max_items: int = UI_TRADE_BATCH_MAX_ITEMS,
    ) -> None:
        self._manager = manager
        self._vp_tape_manager = vp_tape_manager
        self._vp_overlay_manager = vp_overlay_manager
        self._vp_overlay = vp_overlay_consolidator
        self._throttle_ms = throttle_ms
        self._last_dom_ts: float = 0.0
        self._msg_count: int = 0
        self._flow_tracker = FlowTracker()
        self._candle_macd = CandleMacd()
        self._stats_logger = StatsLogger()
        self._agent007 = agent007 or Agent007Engine()
        self._route_count_total = 0
        self._route_time_ms_total = 0.0
        self._type_count: dict[str, int] = {}
        self._type_time_ms: dict[str, float] = {}
        self._throttled_dom_count = 0
        self._invalid_json_count = 0
        self._next_metrics_log_ms = time.monotonic() * 1000 + ROUTER_METRICS_LOG_EVERY_MS
        self._next_broker_snapshot_ms = (
            time.monotonic() * 1000 + BROKER_SNAPSHOT_EVERY_MS
        )
        self._current_trade_date: str | None = None
        self._broker_buy_qty: dict[int, int] = {}
        self._broker_sell_qty: dict[int, int] = {}
        self._broker_buy_fin: dict[int, int] = {}
        self._broker_sell_fin: dict[int, int] = {}
        self._broker_name: dict[int, str] = {}
        self._broker_short_name: dict[int, str] = {}
        self._trade_cache: dict[str, dict[str, int | float | str]] = {}
        self._last_volume_profile_by_ticker: dict[str, dict[str, Any]] = {}
        self._rag = rag_engine
        self._ui_snapshot_interval_ms = max(10, int(ui_snapshot_interval_ms))
        self._ui_trade_batch_max_items = max(10, int(ui_trade_batch_max_items))
        self._ui_latest_by_key: dict[str, dict[str, Any]] = {}
        self._ui_trade_batch: list[dict[str, Any]] = []
        self._ui_trade_overflow_agg: dict[str, dict[str, Any]] = {}
        self._ui_lock = asyncio.Lock()
        self._ui_next_flush_ms = time.monotonic() * 1000 + self._ui_snapshot_interval_ms
        self._ui_aggregated_count = 0
        self._ui_flushed_count = 0
        self._ui_replaced_count = 0
        self._ui_trade_batched_count = 0
        self._ui_flush_duration_ms_total = 0.0
        self._ui_flush_loop_lag_ms_total = 0.0
        self._ui_flush_loop_count = 0
        self._ui_skipped_due_no_clients = 0
        self._last_market_messages: deque[dict[str, Any]] = deque(maxlen=20)
        self._last_trade_messages: deque[dict[str, Any]] = deque(maxlen=20)
        self._last_vp_events: deque[dict[str, Any]] = deque(maxlen=20)
        self._market_counts_by_symbol: defaultdict[str, int] = defaultdict(int)
        self._trade_counts_by_symbol: defaultdict[str, int] = defaultdict(int)
        self._vp_counts_by_symbol: defaultdict[str, int] = defaultdict(int)

    async def route(self, raw: str) -> None:
        """Deserialize, validate, apply throttle, and broadcast if valid."""
        route_start = time.perf_counter()
        msg_type = "unknown"
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON discarded: %s", e)
            self._invalid_json_count += 1
            self._record_metrics(msg_type, route_start)
            return

        if not isinstance(msg, dict):
            logger.warning("Message is not a dict, discarded")
            self._record_metrics(msg_type, route_start)
            return

        self._msg_count += 1
        if self._msg_count == 1:
            logger.info("First market message received from engine (ZMQ -> WS)")

        topic = msg.get("topic")
        msg_type = str(msg.get("type", ""))
        if topic == "market":
            raw_ticker = self._extract_ticker(msg)
            canonical_ticker = canonical_symbol(raw_ticker)
            if canonical_ticker:
                msg["raw_ticker"] = raw_ticker
                msg["ticker"] = canonical_ticker
            elif raw_ticker:
                msg["ticker"] = raw_ticker
            self._market_counts_by_symbol[msg.get("ticker", "UNKNOWN")] += 1
            self._last_market_messages.append(
                {
                    "raw": raw_ticker,
                    "canon": msg.get("ticker"),
                    "type": msg_type,
                    "price": self._extract_price(msg),
                    "qty": self._extract_qty(msg),
                    "keys": sorted(list(msg.keys())),
                }
            )

        if topic == "sync":
            logger.debug("Broadcasting sync message to WebSocket clients")
            await self._manager.broadcast(raw)
            self._record_metrics("sync", route_start)
            return

        if topic == "alert":
            self._ingest_rag(msg)
            await self._manager.broadcast(raw)
            self._stats_logger.log(msg)
            self._record_metrics("alert", route_start)
            return

        if topic == "market":
            if msg_type == "trade":
                price = self._extract_price(msg)
                qty = self._extract_qty(msg)
                trade_symbol = str(msg.get("ticker", "UNKNOWN"))
                self._trade_counts_by_symbol[trade_symbol] += 1
                trade_count = self._trade_counts_by_symbol[trade_symbol]
                if trade_count <= 5 or trade_count % 1000 == 0:
                    logger.info(
                        "[TRADE] raw=%s canon=%s type=%s price=%s qty=%s keys=%s count=%s",
                        msg.get("raw_ticker") or msg.get("ticker"),
                        msg.get("ticker"),
                        msg.get("type"),
                        price,
                        qty,
                        sorted(list(msg.keys())),
                        trade_count,
                    )
                else:
                    logger.debug(
                        "[TRADE] raw=%s canon=%s price=%s qty=%s count=%s",
                        msg.get("raw_ticker") or msg.get("ticker"),
                        msg.get("ticker"),
                        price,
                        qty,
                        trade_count,
                    )
                self._last_trade_messages.append(
                    {
                        "raw": msg.get("raw_ticker") or msg.get("ticker"),
                        "canon": msg.get("ticker"),
                        "price": price,
                        "qty": qty,
                    }
                )
                self._accumulate_broker_trade(msg)
                bundle: list[dict[str, Any]] = []
                inversions = self._flow_tracker.on_trade(msg)
                for inv in inversions:
                    self._agent007.on_flow_inversion(inv)
                    bundle.append(inv)
                    self._stats_logger.log(inv)
                macd_msg = self._candle_macd.on_trade(msg)
                if macd_msg is not None:
                    self._agent007.on_macd(macd_msg)
                    bundle.append(macd_msg)
                st = self._agent007.on_trade(msg)
                if st is not None and self._agent007.should_broadcast(st):
                    bundle.append(st)
                snap = self._broker_snapshot_if_due()
                if snap is not None:
                    await self._enqueue_latest_visual(snap)
                await self._enqueue_trade(msg)
                self._ingest_rag_bundle(bundle)
                await self._send_ws_payloads(bundle)
                self._stats_logger.log(msg)
                self._record_metrics(msg_type, route_start)
                return
            if msg_type == "daily":
                td = str(msg.get("trade_date", "") or "").strip()
                if td and td != self._current_trade_date:
                    self._current_trade_date = td
                    self._reset_broker_accumulators()

            if msg_type in ("volume_profile", "tape_intelligence"):
                msg_work = msg
                if msg_type == "tape_intelligence":
                    msg_work = self._merge_tape_with_last_volume_profile(msg)
                msg_e = await asyncio.to_thread(enrich_vp_ti_message, msg_work)
                if msg_type == "volume_profile":
                    ticker = str(msg_e.get("ticker", "") or "").strip().upper()
                    if ticker:
                        msg_e["source"] = "engine_volume_profile"
                        msg_e["updated_at"] = time.time()
                        self._last_volume_profile_by_ticker[ticker] = msg_e
                        self._vp_counts_by_symbol[ticker] += 1
                        vp_count = self._vp_counts_by_symbol[ticker]
                        self._last_vp_events.append(
                            {
                                "symbol": ticker,
                                "total": msg_e.get("total_vol"),
                                "poc": msg_e.get("poc"),
                                "vah": msg_e.get("vah"),
                                "val": msg_e.get("val"),
                                "source": msg_e.get("source"),
                                "updated_at": msg_e.get("updated_at"),
                            }
                        )
                        log_fn = logger.info if vp_count <= 5 or vp_count % 200 == 0 else logger.debug
                        log_fn(
                            "[VP] symbol=%s levels=%s total=%s poc=%s vah=%s val=%s raw=%s count=%s",
                            ticker,
                            len(msg_e.get("levels") or []),
                            msg_e.get("total_vol"),
                            msg_e.get("poc"),
                            msg_e.get("vah"),
                            msg_e.get("val"),
                            msg_e.get("raw_ticker") or ticker,
                            vp_count,
                        )
                raw_out = json.dumps(msg_e, ensure_ascii=False, separators=(",", ":"))
                self._ingest_rag(msg_e)
                await self._manager.broadcast(raw_out)
                if self._vp_tape_manager is not None:
                    await self._vp_tape_manager.broadcast(raw_out)
                if self._vp_overlay is not None and self._vp_overlay_manager is not None:
                    overlay = self._vp_overlay.feed_market_message(msg_e)
                    if overlay is not None:
                        overlay_e = await asyncio.to_thread(enrich_vp_overlay_payload, overlay)
                        raw_ov = json.dumps(overlay_e, ensure_ascii=False, separators=(",", ":"))
                        await self._vp_overlay_manager.broadcast(raw_ov)
                self._record_metrics(msg_type, route_start)
                return

            if self._is_latest_wins_type(msg):
                await self._enqueue_latest_visual(msg)
                await self._flush_ui_if_due()
                self._record_metrics(msg_type, route_start)
                return
            self._ingest_rag(msg)
            await self._manager.broadcast(raw)
            if msg_type in ("trade", "flow_inversion"):
                self._stats_logger.log(msg)
            await self._flush_ui_if_due()
            self._record_metrics(msg_type, route_start)
            return

        logger.warning("Unknown topic %r, discarded", topic)
        self._record_metrics(msg_type, route_start)

    def _merge_tape_with_last_volume_profile(self, tape_msg: dict[str, Any]) -> dict[str, Any]:
        """Enriquece tape_intelligence com snapshot VP mais recente do ticker."""
        ticker = str(tape_msg.get("ticker", "") or "").strip().upper()
        if not ticker:
            return tape_msg
        vp = self._last_volume_profile_by_ticker.get(ticker)
        if vp is None:
            return tape_msg
        out = dict(tape_msg)
        for field in ("period", "price_step", "total_vol", "poc", "vah", "val", "levels"):
            if field in vp and field not in out:
                out[field] = vp[field]
        for field in ("poc_y", "vah_y", "val_y"):
            if field in vp and field not in out:
                out[field] = vp[field]
        return out

    def _should_throttle(self, msg_type: str) -> bool:
        """Return True if dom_snapshot should be throttled (discarded)."""
        if msg_type != "dom_snapshot":
            return False

        now = time.monotonic() * 1000
        if now - self._last_dom_ts < self._throttle_ms:
            return True
        self._last_dom_ts = now
        return False

    def _is_latest_wins_type(self, msg: dict[str, Any]) -> bool:
        topic = str(msg.get("topic", ""))
        msg_type = str(msg.get("type", ""))
        if topic != "market":
            return False
        if msg_type in ("dom_snapshot", "daily", "broker_snapshot"):
            return True
        if msg_type == "agent007_state" and not bool(msg.get("critical", False)):
            return True
        return False

    def _visual_key(self, msg: dict[str, Any]) -> str:
        msg_type = str(msg.get("type", "unknown"))
        ticker = str(msg.get("ticker", "GLOBAL")).upper()
        channel = str(msg.get("channel", "default"))
        return f"{msg_type}:{ticker}:{channel}"

    async def _enqueue_latest_visual(self, msg: dict[str, Any]) -> None:
        key = self._visual_key(msg)
        async with self._ui_lock:
            if key in self._ui_latest_by_key:
                self._ui_replaced_count += 1
            self._ui_latest_by_key[key] = msg
            self._ui_aggregated_count += 1

    async def _enqueue_trade(self, msg: dict[str, Any]) -> None:
        async with self._ui_lock:
            if len(self._ui_trade_batch) < self._ui_trade_batch_max_items:
                self._ui_trade_batch.append(msg)
                return
            key = self._trade_agg_key(msg)
            cur = self._ui_trade_overflow_agg.get(key)
            qty = int(float(msg.get("qty", 0) or 0))
            if cur is None:
                self._ui_trade_overflow_agg[key] = {
                    "topic": "market",
                    "type": "trade_agg",
                    "ticker": msg.get("ticker"),
                    "price": msg.get("price"),
                    "side": msg.get("side") or msg.get("aggressor") or "unknown",
                    "qty": qty,
                    "count": 1,
                }
            else:
                cur["qty"] = int(cur.get("qty", 0)) + qty
                cur["count"] = int(cur.get("count", 0)) + 1

    def _trade_agg_key(self, msg: dict[str, Any]) -> str:
        ticker = str(msg.get("ticker", "GLOBAL")).upper()
        price = str(msg.get("price", "0"))
        side = str(msg.get("side") or msg.get("aggressor") or "unknown").lower()
        return f"{ticker}:{price}:{side}"

    async def _flush_ui_if_due(self) -> None:
        now_ms = time.monotonic() * 1000
        if now_ms < self._ui_next_flush_ms:
            return
        await self.flush_ui_once()

    async def flush_ui_once(self) -> None:
        flush_start = time.perf_counter()
        now_ms = time.monotonic() * 1000
        lag_ms = max(0.0, now_ms - self._ui_next_flush_ms)
        self._ui_next_flush_ms = now_ms + self._ui_snapshot_interval_ms
        self._ui_flush_loop_count += 1
        self._ui_flush_loop_lag_ms_total += lag_ms

        async with self._ui_lock:
            latest_items = list(self._ui_latest_by_key.values())
            self._ui_latest_by_key.clear()
            trade_items = list(self._ui_trade_batch)
            overflow = list(self._ui_trade_overflow_agg.values())
            self._ui_trade_batch.clear()
            self._ui_trade_overflow_agg.clear()

        if not self._manager.active:
            if latest_items or trade_items or overflow:
                self._ui_skipped_due_no_clients += 1
            return

        payloads: list[dict[str, Any]] = []
        payloads.extend(latest_items)
        if trade_items or overflow:
            items: list[dict[str, Any]] = trade_items + overflow
            payloads.append(
                {
                    "topic": "market",
                    "type": "trade_batch",
                    "items": items,
                    "batch_size": len(items),
                    "overflow_aggregated": len(overflow),
                }
            )
            self._ui_trade_batched_count += len(items)
        if payloads:
            await self._send_ws_payloads(payloads)
            self._ui_flushed_count += 1

        self._ui_flush_duration_ms_total += (time.perf_counter() - flush_start) * 1000.0

    async def ui_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._ui_snapshot_interval_ms / 1000.0)
            await self.flush_ui_once()

    def _record_metrics(self, msg_type: str, route_start: float) -> None:
        elapsed_ms = (time.perf_counter() - route_start) * 1000.0
        self._route_count_total += 1
        self._route_time_ms_total += elapsed_ms
        self._type_count[msg_type] = self._type_count.get(msg_type, 0) + 1
        self._type_time_ms[msg_type] = self._type_time_ms.get(msg_type, 0.0) + elapsed_ms

        now_ms = time.monotonic() * 1000
        if now_ms < self._next_metrics_log_ms:
            return

        avg_total = (
            self._route_time_ms_total / self._route_count_total
            if self._route_count_total
            else 0.0
        )
        top_types = sorted(
            self._type_count.items(),
            key=lambda kv: self._type_time_ms.get(kv[0], 0.0),
            reverse=True,
        )[:3]
        top_types_summary = ", ".join(
            f"{t}:count={self._type_count[t]} avg_ms={self._type_time_ms.get(t, 0.0)/max(1, self._type_count[t]):.3f}"
            for t, _ in top_types
        )
        logger.info(
            "Router metrics: total_count=%s avg_ms=%.3f invalid_json=%s throttled_dom=%s ui_aggregated=%s ui_flushed=%s ui_replaced=%s ui_trade_batched=%s ui_skip_no_clients=%s ui_flush_avg_ms=%.3f ui_flush_lag_avg_ms=%.3f top=[%s]",
            self._route_count_total,
            avg_total,
            self._invalid_json_count,
            self._throttled_dom_count,
            self._ui_aggregated_count,
            self._ui_flushed_count,
            self._ui_replaced_count,
            self._ui_trade_batched_count,
            self._ui_skipped_due_no_clients,
            self._ui_flush_duration_ms_total / max(1, self._ui_flushed_count),
            self._ui_flush_loop_lag_ms_total / max(1, self._ui_flush_loop_count),
            top_types_summary,
        )
        self._next_metrics_log_ms = now_ms + ROUTER_METRICS_LOG_EVERY_MS

    def metrics(self) -> dict[str, float | int]:
        avg_ms = (
            self._route_time_ms_total / self._route_count_total
            if self._route_count_total
            else 0.0
        )
        out: dict[str, float | int] = {
            "route_count_total": self._route_count_total,
            "route_avg_ms": avg_ms,
            "invalid_json_count": self._invalid_json_count,
            "throttled_dom_count": self._throttled_dom_count,
            "ui_aggregated_count": self._ui_aggregated_count,
            "ui_flushed_count": self._ui_flushed_count,
            "ui_replaced_count": self._ui_replaced_count,
            "ui_trade_batched_count": self._ui_trade_batched_count,
            "ui_skipped_due_no_clients": self._ui_skipped_due_no_clients,
            "ui_flush_duration_ms": self._ui_flush_duration_ms_total / max(1, self._ui_flushed_count),
            "ui_flush_loop_lag_ms": self._ui_flush_loop_lag_ms_total / max(1, self._ui_flush_loop_count),
        }
        if self._vp_overlay is not None:
            out.update(self._vp_overlay.metrics())
        return out

    def set_renko_brick_points(self, points: float) -> None:
        """IFR/RSI no Renko: tijolo em pontos (ex.: 42 ou 16), alinhado ao Profit."""
        self._candle_macd.set_renko_brick_points(points)

    def set_ifr_series(self, series: str) -> None:
        """Série do IFR: 42r, 16r ou 30m (candles de 30 min)."""
        self._candle_macd.set_ifr_series(series)

    def warm_macd_snapshot(self, ticker: str) -> Optional[dict[str, Any]]:
        """Snapshot MACD/IFR a partir de estado em disco + CSV (sem esperar trade)."""
        return self._candle_macd.warm_snapshot_message(ticker)

    def latest_volume_profile_snapshot(self, ticker: str) -> Optional[dict[str, Any]]:
        canonical = canonical_symbol(ticker)
        if not canonical:
            return None
        return self._last_volume_profile_by_ticker.get(canonical)

    def vp_overlay_last_snapshot(self, ticker: str) -> Optional[dict[str, Any]]:
        if self._vp_overlay is None:
            return None
        canon = canonical_symbol(ticker) or ticker.strip().upper()
        return self._vp_overlay.last_payload(canon)

    def vp_overlay_debug_snapshot(self, ticker: str) -> dict[str, Any]:
        canon = canonical_symbol(ticker) or ticker.strip().upper()
        if self._vp_overlay is None:
            return {"ok": False, "symbol": canon, "error": "vp_overlay_disabled"}
        vp = self._last_volume_profile_by_ticker.get(canon)
        dbg = self._vp_overlay.debug_state(canon)
        last = self._vp_overlay.last_payload(canon)
        last_publish_age_ms = dbg.get("last_overlay_publish_age_ms")
        last_publish_age_sec = dbg.get("last_overlay_publish_age_sec")
        return {
            "ok": True,
            "symbol": canon,
            "has_volume_profile": vp is not None,
            "volume_profile_age_hint": vp.get("updated_at") if isinstance(vp, dict) else None,
            "last_overlay_publish_age_ms": last_publish_age_ms,
            "last_overlay_publish_age_sec": last_publish_age_sec,
            "consolidator": dbg,
            "last_vp_overlay": last,
            **self._vp_overlay.metrics(),
        }

    def vp_overlay_reset(self, symbol: Optional[str] = None) -> None:
        if self._vp_overlay is not None:
            self._vp_overlay.reset(symbol)

    async def vp_overlay_publish_demo_payload(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        if self._vp_overlay is None or self._vp_overlay_manager is None:
            return None
        sym = self._vp_overlay.inject_demo(payload)
        snap = self._vp_overlay.last_payload(sym)
        if snap is not None:
            snap_e = await asyncio.to_thread(enrich_vp_overlay_payload, snap)
            raw_ov = json.dumps(snap_e, ensure_ascii=False, separators=(",", ":"))
            await self._vp_overlay_manager.broadcast(raw_ov)
            return snap_e
        return snap

    def debug_counters(self) -> dict[str, Any]:
        return {
            "market_counts_by_symbol": dict(self._market_counts_by_symbol),
            "trade_counts_by_symbol": dict(self._trade_counts_by_symbol),
            "last_market_messages": list(self._last_market_messages),
            "last_trade_messages": list(self._last_trade_messages),
            "last_vp_events": list(self._last_vp_events),
        }

    def inject_debug_trade(self, ticker: str, price: float, qty: int) -> dict[str, Any]:
        canon = canonical_symbol(ticker)
        now_ms = int(time.time() * 1000)
        px = float(price)
        qq = max(1, int(qty))
        snap = {
            "topic": "market",
            "type": "volume_profile",
            "ticker": canon,
            "raw_ticker": str(ticker).strip().upper(),
            "period": "manual",
            "timestamp": now_ms,
            "price_step": 5.0,
            "total_vol": qq,
            "poc": px,
            "vah": px,
            "val": px,
            "levels": [
                {
                    "price": px,
                    "total_vol": qq,
                    "bid_vol": qq // 2,
                    "ask_vol": qq - (qq // 2),
                    "pct_of_max": 1.0,
                }
            ],
            "debug_injected": True,
            "source": "debug_inject",
            "updated_at": time.time(),
        }
        self._last_volume_profile_by_ticker[canon] = snap
        self._last_vp_events.append(
            {
                "symbol": canon,
                "total": qq,
                "poc": px,
                "vah": px,
                "val": px,
                "debug_injected": True,
                "source": "debug_inject",
                "updated_at": snap["updated_at"],
            }
        )
        logger.info("[VP_DEBUG] injected trade symbol=%s raw=%s price=%s qty=%s", canon, ticker, px, qq)
        return snap

    def clear_volume_profile(self, symbol: str = "WINFUT") -> None:
        canon = canonical_symbol(symbol)
        if not canon:
            return
        self._last_volume_profile_by_ticker.pop(canon, None)
        # Limpa também agregados internos de VP, se existirem no runtime/branch atual.
        for attr in (
            "_volume_profile_by_price",
            "_volume_by_price",
            "_vp_levels",
            "_profile_levels_by_ticker",
            "_latest_volume_profile",
        ):
            store = getattr(self, attr, None)
            if isinstance(store, dict):
                store.pop(canon, None)
        self._last_vp_events.append(
            {
                "symbol": canon,
                "source": "debug_clear",
                "updated_at": time.time(),
                "total": 0,
                "poc": None,
                "vah": None,
                "val": None,
            }
        )
        logger.info("[VP_DEBUG] cleared symbol=%s", canon)

    def _extract_ticker(self, msg: dict[str, Any]) -> str:
        return str(
            msg.get("ticker")
            or msg.get("symbol")
            or msg.get("asset")
            or msg.get("instrument")
            or msg.get("security")
            or ""
        ).strip().upper()

    def _extract_price(self, msg: dict[str, Any]) -> float | None:
        for k in ("price", "last_price", "trade_price", "preco", "last"):
            v = msg.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    def _extract_qty(self, msg: dict[str, Any]) -> int:
        for k in ("qty", "quantity", "volume", "size", "qtd"):
            v = msg.get(k)
            if v is None:
                continue
            try:
                return int(float(v))
            except (TypeError, ValueError):
                continue
        return 0

    def _reset_broker_accumulators(self) -> None:
        self._broker_buy_qty = {}
        self._broker_sell_qty = {}
        self._broker_buy_fin = {}
        self._broker_sell_fin = {}
        self._broker_name = {}
        self._broker_short_name = {}
        self._trade_cache = {}

    def _trade_cache_key(self, msg: dict, buy_agent: int, sell_agent: int, qty: int, price: float) -> str:
        trade_number = int(msg.get("trade_number") or 0)
        if trade_number > 0:
            ticker = str(msg.get("ticker") or "")
            td = str(msg.get("trade_date") or self._current_trade_date or "")
            return f"{ticker}|{td}|{trade_number}"
        trade_ts = str(msg.get("ts") or "")
        trade_source = str(msg.get("trade_source") or "")
        return f"{trade_source}|{trade_ts}|{buy_agent}|{sell_agent}|{qty}|{price:.8f}"

    def _apply_broker_delta(self, buy_agent: int, sell_agent: int, qty: int, fin: int) -> None:
        self._broker_buy_qty[buy_agent] = self._broker_buy_qty.get(buy_agent, 0) + qty
        self._broker_sell_qty[sell_agent] = self._broker_sell_qty.get(sell_agent, 0) + qty
        self._broker_buy_fin[buy_agent] = self._broker_buy_fin.get(buy_agent, 0) + fin
        self._broker_sell_fin[sell_agent] = self._broker_sell_fin.get(sell_agent, 0) + fin

    def _accumulate_broker_trade(self, msg: dict) -> None:
        try:
            buy_agent = int(msg.get("buy_agent", 0))
            sell_agent = int(msg.get("sell_agent", 0))
            qty = int(float(msg.get("qty", 0)))
            price = float(msg.get("price", 0.0))
        except (TypeError, ValueError):
            return
        if qty == 0:
            return
        fin = int(round(price * qty))
        is_edit = bool(msg.get("is_edit", False))
        key = self._trade_cache_key(msg, buy_agent, sell_agent, qty, price)
        prev = self._trade_cache.get(key)
        if prev is not None:
            prev_buy = int(prev.get("buy_agent", 0))
            prev_sell = int(prev.get("sell_agent", 0))
            prev_qty = int(prev.get("qty", 0))
            prev_fin = int(prev.get("fin", 0))
            if (
                prev_buy == buy_agent
                and prev_sell == sell_agent
                and prev_qty == qty
                and prev_fin == fin
            ):
                return
            # correction/edit: rollback previous version then apply newest
            self._apply_broker_delta(prev_buy, prev_sell, -prev_qty, -prev_fin)
        elif is_edit:
            # edit sem baseline local: aplica como novo (melhor esforço)
            pass

        self._apply_broker_delta(buy_agent, sell_agent, qty, fin)
        self._trade_cache[key] = {
            "buy_agent": buy_agent,
            "sell_agent": sell_agent,
            "qty": qty,
            "fin": fin,
        }

        buy_name = msg.get("buy_agent_name")
        sell_name = msg.get("sell_agent_name")
        buy_short = msg.get("buy_agent_short_name")
        sell_short = msg.get("sell_agent_short_name")
        if isinstance(buy_name, str) and buy_name.strip():
            self._broker_name[buy_agent] = buy_name
        if isinstance(sell_name, str) and sell_name.strip():
            self._broker_name[sell_agent] = sell_name
        if isinstance(buy_short, str) and buy_short.strip():
            self._broker_short_name[buy_agent] = buy_short
        if isinstance(sell_short, str) and sell_short.strip():
            self._broker_short_name[sell_agent] = sell_short

    def _broker_snapshot_if_due(self) -> Optional[dict[str, Any]]:
        now_ms = time.monotonic() * 1000
        if now_ms < self._next_broker_snapshot_ms:
            return None
        self._next_broker_snapshot_ms = now_ms + BROKER_SNAPSHOT_EVERY_MS
        return {
            "topic": "market",
            "type": "broker_snapshot",
            "trade_date": self._current_trade_date,
            "buy_qty": self._broker_buy_qty,
            "sell_qty": self._broker_sell_qty,
            "buy_fin": self._broker_buy_fin,
            "sell_fin": self._broker_sell_fin,
            "agent_name": self._broker_name,
            "agent_short_name": self._broker_short_name,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    async def _send_ws_payloads(self, payloads: list[dict[str, Any]]) -> None:
        """One WebSocket frame: single JSON or ws_batch when multiple payloads."""
        if not payloads:
            return
        if len(payloads) == 1:
            await self._manager.broadcast(json.dumps(payloads[0]))
            return
        await self._manager.broadcast(
            json.dumps({"topic": "ws_batch", "items": payloads})
        )

    def _ingest_rag_bundle(self, payloads: list[dict[str, Any]]) -> None:
        for payload in payloads:
            self._ingest_rag(payload)

    def _ingest_rag(self, msg: dict[str, Any]) -> None:
        if self._rag is None:
            return
        try:
            self._rag.ingest(msg)
        except Exception:  # pragma: no cover - proteção defensiva
            logger.exception("RAG ingest failed for topic=%s type=%s", msg.get("topic"), msg.get("type"))
