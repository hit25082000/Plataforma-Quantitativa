"""Manages the set of connected WebSocket clients."""

import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket client."""
        await ws.accept()
        self.active.add(ws)
        logger.info("WebSocket client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket client from the active set."""
        self.active.discard(ws)
        logger.info("WebSocket client disconnected. Total: %d", len(self.active))

    async def broadcast(self, message: str) -> None:
        """Send message to all connected clients. Remove failed clients silently."""
        disconnected: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning("Failed to send to client: %s", e)
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)
