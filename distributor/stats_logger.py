"""Stats logger: append CSV lines for alert, trade, flow_inversion."""

import csv
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = "logs"
CSV_FIELDS = [
    "ts", "topic", "type", "ticker", "price", "qty", "agent", "rule", "label",
    "buy_agent", "sell_agent", "previous_delta", "current_delta", "agent_name",
]


class StatsLogger:
    def __init__(self, log_dir: Optional[str] = None) -> None:
        self._log_dir = os.path.abspath(log_dir or DEFAULT_LOG_DIR)
        self._file_handle: Optional[Any] = None
        self._writer: Optional[csv.DictWriter] = None
        self._date: Optional[str] = None
        self._flush_every_rows = int(os.environ.get("STATS_FLUSH_EVERY_ROWS", "200"))
        self._flush_every_ms = int(os.environ.get("STATS_FLUSH_EVERY_MS", "1000"))
        self._rows_since_flush = 0
        self._last_flush_ms = int(time.monotonic() * 1000)

    def _ensure_file(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._date == today and self._file_handle is not None:
            return
        if self._file_handle is not None:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None
            self._writer = None
        os.makedirs(self._log_dir, exist_ok=True)
        path = os.path.join(self._log_dir, f"stats_{today}.csv")
        try:
            exists = os.path.exists(path)
            self._file_handle = open(path, "a", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._file_handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if not exists:
                self._writer.writeheader()
                self._rows_since_flush += 1
            self._last_flush_ms = int(time.monotonic() * 1000)
            self._date = today
        except OSError as e:
            logger.warning("StatsLogger could not open %s: %s", path, e)

    def _row(self, msg: dict[str, Any]) -> dict[str, str]:
        topic = msg.get("topic") or ""
        msg_type = msg.get("type") or ""
        ts = msg.get("ts") or ""
        row = {"ts": ts, "topic": topic, "type": msg_type}
        if "ticker" in msg:
            row["ticker"] = str(msg["ticker"])
        if "price" in msg:
            row["price"] = str(msg.get("price"))
        if "qty" in msg:
            row["qty"] = str(msg.get("qty"))
        if "rule" in msg:
            row["rule"] = str(msg.get("rule"))
        if "label" in msg:
            row["label"] = str(msg.get("label"))
        if "buy_agent_name" in msg:
            row["buy_agent"] = str(msg.get("buy_agent_name", ""))
        if "sell_agent_name" in msg:
            row["sell_agent"] = str(msg.get("sell_agent_name", ""))
        if "agent_name" in msg:
            row["agent_name"] = str(msg.get("agent_name", ""))
        if "previous_delta" in msg:
            row["previous_delta"] = str(msg.get("previous_delta"))
        if "current_delta" in msg:
            row["current_delta"] = str(msg.get("current_delta"))
        return row

    def _maybe_flush(self) -> None:
        if self._file_handle is None:
            return
        now_ms = int(time.monotonic() * 1000)
        if (
            self._rows_since_flush >= self._flush_every_rows
            or (now_ms - self._last_flush_ms) >= self._flush_every_ms
        ):
            self._file_handle.flush()
            self._rows_since_flush = 0
            self._last_flush_ms = now_ms

    def log(self, msg: dict[str, Any]) -> None:
        topic = msg.get("topic")
        msg_type = msg.get("type", "")
        if topic == "alert":
            self._ensure_file()
            if self._writer:
                self._writer.writerow(self._row(msg))
                self._rows_since_flush += 1
                self._maybe_flush()
            return
        if topic == "market" and msg_type in ("trade", "flow_inversion"):
            self._ensure_file()
            if self._writer:
                self._writer.writerow(self._row(msg))
                self._rows_since_flush += 1
                self._maybe_flush()
