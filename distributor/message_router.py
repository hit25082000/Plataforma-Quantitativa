"""Message routing with JSON validation and dom_snapshot throttling."""

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

class MessageRouter:
    """Routes messages from ZMQ to WebSocket clients with validation and throttle."""

    def __init__(self, manager: "ConnectionManager", throttle_ms: int) -> None:
        self._manager = manager
        self._throttle_ms = throttle_ms
        self._last_dom_ts: float = 0.0
        self._msg_count: int = 0

    async def route(self, raw: str) -> None:
        """Deserialize, validate, apply throttle, and broadcast if valid."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON discarded: %s", e)
            return

        if not isinstance(msg, dict):
            logger.warning("Message is not a dict, discarded")
            return

        self._msg_count += 1
        if self._msg_count == 1:
            logger.info("First market message received from engine (ZMQ -> WS)")

        topic = msg.get("topic")
        msg_type = msg.get("type", "")

        if topic == "alert":
            # Alertas nunca são throttled
            await self._manager.broadcast(raw)
            return

        if topic == "market":
            if self._should_throttle(msg_type):
                return
            await self._manager.broadcast(raw)
            return

        logger.warning("Unknown topic %r, discarded", topic)

    def _should_throttle(self, msg_type: str) -> bool:
        """Return True if dom_snapshot should be throttled (discarded)."""
        if msg_type != "dom_snapshot":
            return False

        now = time.monotonic() * 1000
        if now - self._last_dom_ts < self._throttle_ms:
            return True
        self._last_dom_ts = now
        return False
