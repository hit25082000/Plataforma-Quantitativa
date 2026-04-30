"""Manages WebSocket clients with per-client backpressure queues."""

import asyncio
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(
        self,
        client_queue_maxsize: int = 1,
        dropped_metric_key: str = "ui_client_queue_dropped",
    ) -> None:
        self.active: set[WebSocket] = set()
        self._client_queue_maxsize = max(1, int(client_queue_maxsize))
        self._dropped_metric_key = dropped_metric_key
        self._client_queues: dict[WebSocket, asyncio.Queue[str]] = {}
        self._client_tasks: dict[WebSocket, asyncio.Task[None]] = {}
        self._client_queue_dropped = 0

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket client."""
        await ws.accept()
        self.active.add(ws)
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._client_queue_maxsize)
        self._client_queues[ws] = q
        self._client_tasks[ws] = asyncio.create_task(self._client_sender(ws, q))
        logger.info("WebSocket client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket client from the active set."""
        self.active.discard(ws)
        q = self._client_queues.pop(ws, None)
        if q is not None:
            try:
                q.put_nowait("")
            except asyncio.QueueFull:
                pass
        task = self._client_tasks.pop(ws, None)
        if task is not None:
            task.cancel()
        logger.info("WebSocket client disconnected. Total: %d", len(self.active))

    async def broadcast(self, message: str) -> None:
        """Enqueue message for all clients; drop stale frame if queue is full."""
        if not self.active:
            return

        clients = list(self.active)
        for ws in clients:
            q = self._client_queues.get(ws)
            if q is None:
                continue
            if q.full():
                try:
                    _ = q.get_nowait()
                    self._client_queue_dropped += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                self._client_queue_dropped += 1

    def metrics(self) -> dict[str, int]:
        return {
            "connected_ws_clients": len(self.active),
            self._dropped_metric_key: self._client_queue_dropped,
        }

    async def _client_sender(self, ws: WebSocket, q: asyncio.Queue[str]) -> None:
        while ws in self.active:
            try:
                msg = await q.get()
                if msg == "" and ws not in self.active:
                    break
                await ws.send_text(msg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to send to client: %s", exc)
                self.disconnect(ws)
                break
