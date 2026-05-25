"""Runtime startup/readiness state for distributor health endpoints."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_feed_live_stale_ms() -> int:
    raw = os.environ.get("DISTRIBUTOR_FEED_LIVE_STALE_MS", "15000")
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = 15000
    return max(1000, parsed)


FEED_LIVE_STALE_MS = _read_feed_live_stale_ms()


class DistributorStartupState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._service_started_at_iso = utc_now_iso()
        self._ready = False
        self._ipc_mode = "unknown"
        self._ipc_status = "starting"
        self._error: str | None = None
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._ws_clients = 0
        self._messages_received_total = 0
        self._messages_sent_total = 0
        self._last_market_event_at: str | None = None
        self._last_market_event_monotonic: float | None = None
        self._last_ws_send_at: str | None = None
        self._first_market_event_logged = False

    def reset(self, *, ipc_mode: str = "unknown") -> None:
        with self._lock:
            self._started_at = time.monotonic()
            self._service_started_at_iso = utc_now_iso()
            self._ready = False
            self._ipc_mode = ipc_mode
            self._ipc_status = "starting"
            self._error = None
            self._last_error = None
            self._last_error_at = None
            self._ws_clients = 0
            self._messages_received_total = 0
            self._messages_sent_total = 0
            self._last_market_event_at = None
            self._last_market_event_monotonic = None
            self._last_ws_send_at = None
            self._first_market_event_logged = False

    def set_ipc_mode(self, mode: str) -> None:
        with self._lock:
            self._ipc_mode = (mode or "unknown").strip().lower() or "unknown"

    def set_status(self, status: str) -> None:
        with self._lock:
            self._ipc_status = status.strip() if status else "starting"

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self._ready = bool(ready)

    def set_error(self, error: str | None) -> None:
        with self._lock:
            self._error = (error or "").strip() or None
            if self._error:
                self._last_error = self._error
                self._last_error_at = utc_now_iso()

    def record_error(self, error: str | None) -> None:
        with self._lock:
            self._last_error = (error or "").strip() or None
            if self._last_error:
                self._last_error_at = utc_now_iso()

    def clear_error(self) -> None:
        with self._lock:
            self._error = None

    def ws_client_connected(self) -> None:
        with self._lock:
            self._ws_clients += 1

    def ws_client_disconnected(self) -> None:
        with self._lock:
            self._ws_clients = max(0, self._ws_clients - 1)

    def record_message_received(self, *, is_market_event: bool) -> bool:
        with self._lock:
            self._messages_received_total += 1
            if is_market_event:
                self._last_market_event_at = utc_now_iso()
                self._last_market_event_monotonic = time.monotonic()
                if not self._first_market_event_logged:
                    self._first_market_event_logged = True
                    return True
            return False

    def record_message_sent(self, count: int = 1) -> None:
        safe_count = max(0, int(count))
        if safe_count <= 0:
            return
        with self._lock:
            self._messages_sent_total += safe_count
            self._last_ws_send_at = utc_now_iso()

    def messages_sent_total(self) -> int:
        with self._lock:
            return self._messages_sent_total

    def messages_received_total(self) -> int:
        with self._lock:
            return self._messages_received_total

    def _is_feed_live_locked(self) -> bool:
        if self._last_market_event_monotonic is None:
            return False
        age_ms = max(0.0, (time.monotonic() - self._last_market_event_monotonic) * 1000.0)
        return age_ms <= FEED_LIVE_STALE_MS

    def _rates_locked(self) -> tuple[float, float]:
        uptime = max(0.001, time.monotonic() - self._started_at)
        recv_rate = float(self._messages_received_total) / uptime
        send_rate = float(self._messages_sent_total) / uptime
        return recv_rate, send_rate

    def debug_status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            recv_rate, send_rate = self._rates_locked()
            return {
                "ok": True,
                "ready": self._ready,
                "feed_live": self._is_feed_live_locked(),
                "ipc_mode": self._ipc_mode,
                "ipc_status": self._ipc_status,
                "ws_clients": self._ws_clients,
                "messages_received_total": self._messages_received_total,
                "messages_sent_total": self._messages_sent_total,
                "messages_received_per_sec": round(recv_rate, 4),
                "messages_sent_per_sec": round(send_rate, 4),
                "last_market_event_at": self._last_market_event_at,
                "last_ws_send_at": self._last_ws_send_at,
                "error": self._error,
                "last_error": self._last_error,
                "last_error_at": self._last_error_at,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            uptime = max(0.0, time.monotonic() - self._started_at)
            recv_rate, send_rate = self._rates_locked()
            return {
                "ok": True,
                "service": "distributor",
                "ready": self._ready,
                "feed_live": self._is_feed_live_locked(),
                "ipc_mode": self._ipc_mode,
                "ipc_status": self._ipc_status,
                "uptime_seconds": round(uptime, 3),
                "error": self._error,
                "last_error": self._last_error,
                "last_error_at": self._last_error_at,
                "ws_clients": self._ws_clients,
                "messages_received_total": self._messages_received_total,
                "messages_sent_total": self._messages_sent_total,
                "messages_received_per_sec": round(recv_rate, 4),
                "messages_sent_per_sec": round(send_rate, 4),
                "last_market_event_at": self._last_market_event_at,
                "last_ws_send_at": self._last_ws_send_at,
                "started_at": self._service_started_at_iso,
            }


startup_state = DistributorStartupState()
