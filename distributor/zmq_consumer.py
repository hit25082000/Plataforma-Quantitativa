"""ZMQ SUB consumer running in a dedicated thread."""

import asyncio
import json
import logging
import os
import threading
import time
from typing import FrozenSet, Optional
from urllib.parse import urlparse

import zmq
from startup_state import startup_state

try:
    from egress_allowlist import enforce_endpoint_ip_allowlist
    _HAS_EGRESS_ALLOWLIST = True
except ImportError:  # fallback se rodando fora do pacote distributor
    _HAS_EGRESS_ALLOWLIST = False

logger = logging.getLogger(__name__)

RCVTIMEO_MS = 100  # evita bloquear shutdown


class ZmqConsumer:
    """Consumes messages from ZMQ PUB socket and pushes to asyncio.Queue."""

    def __init__(
        self,
        address: str,
        queue: asyncio.Queue[str],
        dom_soft_limit_pct: int = 70,
        allowed_ips_raw: Optional[str] = None,
        *,
        market_type_allowlist: Optional[FrozenSet[str]] = None,
    ) -> None:
        self._address = address
        self._queue = queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._dropped_count = 0
        self._dropped_low_priority = 0
        self._rescued_trades = 0
        self._evicted_dom = 0
        safe_pct = max(1, min(int(dom_soft_limit_pct), 99))
        maxsize = max(int(getattr(queue, "maxsize", 0)), 0)
        self._dom_soft_limit = int(maxsize * safe_pct / 100) if maxsize > 0 else 0
        # Allowlist de egress: lê ZMQ_ALLOWED_IPS ou usa o parâmetro explícito
        self._allowed_ips_raw: Optional[str] = (
            allowed_ips_raw
            if allowed_ips_raw is not None
            else os.environ.get("ZMQ_ALLOWED_IPS", "").strip() or None
        )
        self._market_type_allowlist: Optional[FrozenSet[str]] = market_type_allowlist
        self._received_total = 0
        self._first_event_logged = False

    @staticmethod
    def _topic_and_type(raw: str) -> tuple[str, str]:
        try:
            msg = json.loads(raw)
            if isinstance(msg, dict):
                return str(msg.get("topic", "")), str(msg.get("type", ""))
        except json.JSONDecodeError:
            pass
        return "", ""

    @staticmethod
    def _message_type(raw: str) -> str:
        """Parse once; used on hot path and during queue eviction."""
        try:
            msg = json.loads(raw)
            if isinstance(msg, dict):
                return str(msg.get("type", ""))
        except json.JSONDecodeError:
            return ""
        return ""

    @staticmethod
    def _is_low_priority_type(msg_type: str) -> bool:
        """Messages that can be dropped first under pressure."""
        return msg_type in ("wall_remove",)

    def _evict_one_dom_snapshot(self) -> bool:
        # Accessing the internal deque keeps this operation O(n) and avoids
        # dequeue/requeue storms during overload.
        q = self._queue._queue  # type: ignore[attr-defined]
        for idx, item in enumerate(q):
            # Cheap filter: skip full JSON parse for frames that cannot be dom_snapshot.
            if "dom_snapshot" not in item:
                continue
            if self._message_type(item) == "dom_snapshot":
                del q[idx]
                self._evicted_dom += 1
                return True
        return False

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start the consumer thread (daemon). Pass the main thread's event loop so call_soon_threadsafe works."""
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("[distributor.consumer] start_requested endpoint=%s mode=zmq", self._address)

    def stop(self) -> None:
        """Signal the consumer to stop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def is_alive(self) -> bool:
        """Return True if the consumer thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def metrics(self) -> dict[str, int]:
        """Best-effort counters for queue pressure diagnostics."""
        return {
            "received_total": self._received_total,
            "dropped_dom": self._dropped_count,
            "dropped_low_priority": self._dropped_low_priority,
            "rescued_trade_like": self._rescued_trades,
            "evicted_dom": self._evicted_dom,
        }

    def _put_msg(self, raw: str) -> None:
        """Put message in queue with trade-preserving drop policy."""
        if self._market_type_allowlist is not None:
            topic, typ = self._topic_and_type(raw)
            if topic == "alert":
                msg_type = typ or "alert"
            elif topic == "market":
                if typ not in self._market_type_allowlist:
                    return
                msg_type = typ
            else:
                return
        else:
            msg_type = self._message_type(raw)
        is_dom = msg_type == "dom_snapshot"
        is_trade_like = msg_type in ("trade", "flow_inversion")
        is_vp_ti = msg_type in ("volume_profile", "tape_intelligence")
        is_low_priority = self._is_low_priority_type(msg_type)

        # Prevent queue growth into runaway latency: drop low-priority frames early.
        if (is_dom or is_low_priority) and self._dom_soft_limit > 0:
            if self._queue.qsize() >= self._dom_soft_limit:
                if is_dom:
                    self._dropped_count += 1
                    if self._dropped_count % 100 == 0:
                        logger.warning(
                            "Market queue pressure: preemptively dropped %s dom_snapshot messages (soft_limit=%s)",
                            self._dropped_count,
                            self._dom_soft_limit,
                        )
                else:
                    self._dropped_low_priority += 1
                    if self._dropped_low_priority % 500 == 0:
                        logger.warning(
                            "Market queue pressure: preemptively dropped %s low-priority messages (soft_limit=%s)",
                            self._dropped_low_priority,
                            self._dom_soft_limit,
                        )
                return
        try:
            self._queue.put_nowait(raw)
        except asyncio.QueueFull:
            if is_dom:
                self._dropped_count += 1
                if self._dropped_count % 100 == 0:
                    logger.warning(
                        "Market queue full: dropped %s dom_snapshot messages",
                        self._dropped_count,
                    )
                return
            if is_low_priority:
                self._dropped_low_priority += 1
                if self._dropped_low_priority % 500 == 0:
                    logger.warning(
                        "Market queue full: dropped %s low-priority messages",
                        self._dropped_low_priority,
                    )
                return
            if (is_trade_like or is_vp_ti) and self._evict_one_dom_snapshot():
                try:
                    self._queue.put_nowait(raw)
                    self._rescued_trades += 1
                    if self._rescued_trades % 50 == 0:
                        logger.warning(
                            "Queue pressure: rescued %s trade-like messages by evicting dom_snapshot (%s evictions)",
                            self._rescued_trades,
                            self._evicted_dom,
                        )
                    return
                except asyncio.QueueFull:
                    pass
            logger.warning("Market queue full, discarding non-dom message")

    def _check_egress_allowlist(self) -> bool:
        """Valida endpoint TCP contra ZMQ_ALLOWED_IPS. Retorna True se permitido."""
        if not self._allowed_ips_raw or not _HAS_EGRESS_ALLOWLIST:
            return True
        # ZMQ address é tcp://host:port — extrai host
        address = self._address.strip()
        # Normaliza para URL válida para urlparse
        url_form = address if "://" in address else f"tcp://{address}"
        try:
            enforce_endpoint_ip_allowlist(
                endpoint_url=url_form,
                raw_allowlist=self._allowed_ips_raw,
                env_var_name="ZMQ_ALLOWED_IPS",
                endpoint_label="ZMQ",
            )
            return True
        except RuntimeError as exc:
            logger.error("ZMQ egress bloqueado por ZMQ_ALLOWED_IPS: %s", exc)
            return False

    def _allow_raw_fast(self, raw: str) -> bool:
        """Fast pre-filter in socket thread to avoid flooding the event loop."""
        if self._market_type_allowlist is None:
            return True
        # Accept alert frames without expensive JSON parse.
        if '"topic":"alert"' in raw or '"topic": "alert"' in raw:
            return True
        if '"topic":"market"' not in raw and '"topic": "market"' not in raw:
            return False
        for typ in self._market_type_allowlist:
            token_compact = f'"type":"{typ}"'
            token_spaced = f'"type": "{typ}"'
            if token_compact in raw or token_spaced in raw:
                return True
        return False

    def _run(self) -> None:
        """Loop in dedicated thread: receive from ZMQ, push to queue; reconecta se a ligacao cair."""
        if not self._check_egress_allowlist():
            logger.error(
                "[distributor.consumer] error=allowlist_blocked endpoint=%s detail=ZMQ_ALLOWED_IPS",
                self._address,
            )
            startup_state.record_error(
                f"consumer_allowlist_blocked endpoint={self._address}"
            )
            return

        loop = self._loop
        reconnect_s = 0.5
        max_reconnect_s = 20.0
        while not self._stop_event.is_set():
            ctx = zmq.Context()
            sock = ctx.socket(zmq.SUB)
            sock.setsockopt(zmq.RCVTIMEO, RCVTIMEO_MS)
            try:
                sock.connect(self._address)
                sock.setsockopt(zmq.SUBSCRIBE, b"")
                logger.info(
                    "[distributor.consumer] loop_started endpoint=%s mode=zmq",
                    self._address,
                )
            except zmq.ZMQError as e:
                logger.error(
                    "[distributor.consumer] error=connect_failed endpoint=%s detail=%s",
                    self._address,
                    e,
                )
                startup_state.record_error(
                    f"consumer_connect_failed endpoint={self._address} detail={e}"
                )
                sock.close()
                ctx.term()
                if self._stop_event.is_set():
                    break
                time.sleep(min(reconnect_s, max_reconnect_s))
                reconnect_s = min(reconnect_s * 1.4, max_reconnect_s)
                continue

            reconnect_s = 0.5
            try:
                while not self._stop_event.is_set():
                    try:
                        raw = sock.recv_string()
                        self._received_total += 1
                        if not self._first_event_logged:
                            topic, msg_type = self._topic_and_type(raw)
                            logger.info(
                                "[distributor.consumer] first_event_received endpoint=%s topic=%s type=%s",
                                self._address,
                                topic or "?",
                                msg_type or "?",
                            )
                            self._first_event_logged = True
                        if self._received_total == 1 or self._received_total % 1000 == 0:
                            logger.info(
                                "[distributor.consumer] received_total=%s endpoint=%s",
                                self._received_total,
                                self._address,
                            )
                        if not self._allow_raw_fast(raw):
                            continue
                        if loop is not None:
                            loop.call_soon_threadsafe(self._put_msg, raw)
                        else:
                            self._put_msg(raw)
                    except zmq.Again:
                        continue
                    except zmq.ZMQError as e:
                        logger.error(
                            "[distributor.consumer] error=recv_failed endpoint=%s detail=%s",
                            self._address,
                            e,
                        )
                        startup_state.record_error(f"zmq_recv_error: {e}")
                        break
                    except Exception as e:  # noqa: BLE001
                        logger.exception(
                            "[distributor.consumer] error=loop_exception endpoint=%s detail=%s",
                            self._address,
                            e,
                        )
                        startup_state.record_error(f"zmq_loop_error: {e}")
                        break
            finally:
                sock.close()
                ctx.term()

            if not self._stop_event.is_set():
                logger.info(
                    "[distributor.consumer] reconnect_scheduled endpoint=%s delay_s=%.1f",
                    self._address,
                    reconnect_s,
                )
                time.sleep(reconnect_s)
                reconnect_s = min(reconnect_s * 1.4, max_reconnect_s)

        logger.info("[distributor.consumer] stopped endpoint=%s", self._address)
