"""Message routing with JSON validation and dom_snapshot throttling."""

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

from agent_007 import Agent007Engine
from candle_macd import CandleMacd
from config import BROKER_SNAPSHOT_EVERY_MS, ROUTER_METRICS_LOG_EVERY_MS
from flow_tracker import FlowTracker
from stats_logger import StatsLogger

if TYPE_CHECKING:
    from connection_manager import ConnectionManager
    from realtime_rag import RealtimeRagEngine

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes messages from ZMQ to WebSocket clients with validation and throttle."""

    def __init__(
        self,
        manager: "ConnectionManager",
        throttle_ms: int,
        agent007: Optional[Agent007Engine] = None,
        rag_engine: Optional["RealtimeRagEngine"] = None,
    ) -> None:
        self._manager = manager
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
        self._rag = rag_engine

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
                    bundle.append(snap)
                bundle.append(msg)
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

            if self._should_throttle(msg_type):
                self._throttled_dom_count += 1
                self._record_metrics(msg_type, route_start)
                return
            self._ingest_rag(msg)
            await self._manager.broadcast(raw)
            if msg_type in ("trade", "flow_inversion"):
                self._stats_logger.log(msg)
            self._record_metrics(msg_type, route_start)
            return

        logger.warning("Unknown topic %r, discarded", topic)
        self._record_metrics(msg_type, route_start)

    def _should_throttle(self, msg_type: str) -> bool:
        """Return True if dom_snapshot should be throttled (discarded)."""
        if msg_type != "dom_snapshot":
            return False

        now = time.monotonic() * 1000
        if now - self._last_dom_ts < self._throttle_ms:
            return True
        self._last_dom_ts = now
        return False

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
            "Router metrics: total_count=%s avg_ms=%.3f invalid_json=%s throttled_dom=%s top=[%s]",
            self._route_count_total,
            avg_total,
            self._invalid_json_count,
            self._throttled_dom_count,
            top_types_summary,
        )
        self._next_metrics_log_ms = now_ms + ROUTER_METRICS_LOG_EVERY_MS

    def metrics(self) -> dict[str, float | int]:
        avg_ms = (
            self._route_time_ms_total / self._route_count_total
            if self._route_count_total
            else 0.0
        )
        return {
            "route_count_total": self._route_count_total,
            "route_avg_ms": avg_ms,
            "invalid_json_count": self._invalid_json_count,
            "throttled_dom_count": self._throttled_dom_count,
        }

    def set_renko_brick_points(self, points: float) -> None:
        """IFR/RSI no Renko: tijolo em pontos (ex.: 42 ou 16), alinhado ao Profit."""
        self._candle_macd.set_renko_brick_points(points)

    def set_ifr_series(self, series: str) -> None:
        """Série do IFR: 42r, 16r ou 30m (candles de 30 min)."""
        self._candle_macd.set_ifr_series(series)

    def warm_macd_snapshot(self, ticker: str) -> Optional[dict[str, Any]]:
        """Snapshot MACD/IFR a partir de estado em disco + CSV (sem esperar trade)."""
        return self._candle_macd.warm_snapshot_message(ticker)

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
