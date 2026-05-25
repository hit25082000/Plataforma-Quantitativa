"""Manages WebSocket clients with per-client backpressure queues."""

import asyncio
import logging
import time
from fastapi import WebSocket

from startup_state import startup_state

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
        self._broadcast_calls = 0
        self._broadcast_duration_ms_total = 0.0

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket client."""
        await ws.accept()
        self.active.add(ws)
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._client_queue_maxsize)
        self._client_queues[ws] = q
        self._client_tasks[ws] = asyncio.create_task(self._client_sender(ws, q))
        logger.info("[distributor.ws] client_connected count=%d", len(self.active))

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
        logger.info("[distributor.ws] client_disconnected count=%d", len(self.active))

    async def broadcast(self, message: str) -> None:
        """Enqueue message for all clients; drop stale frame if queue is full."""
        started = time.perf_counter()
        if not self.active:
            self._broadcast_calls += 1
            self._broadcast_duration_ms_total += (time.perf_counter() - started) * 1000.0
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
        self._broadcast_calls += 1
        self._broadcast_duration_ms_total += (time.perf_counter() - started) * 1000.0

    def metrics(self) -> dict[str, int | float]:
        queue_depth_total = 0
        queue_depth_max = 0
        for q in self._client_queues.values():
            depth = q.qsize()
            queue_depth_total += depth
            if depth > queue_depth_max:
                queue_depth_max = depth
        avg_broadcast_ms = (
            self._broadcast_duration_ms_total / self._broadcast_calls
            if self._broadcast_calls > 0
            else 0.0
        )
        return {
            "connected_ws_clients": len(self.active),
            self._dropped_metric_key: self._client_queue_dropped,
            "queue_depth_total": queue_depth_total,
            "queue_depth_max": queue_depth_max,
            "broadcast_calls_total": self._broadcast_calls,
            "avg_broadcast_ms": round(avg_broadcast_ms, 4),
        }

    async def _client_sender(self, ws: WebSocket, q: asyncio.Queue[str]) -> None:
        while ws in self.active:
            try:
                msg = await q.get()
                if msg == "" and ws not in self.active:
                    break
                await ws.send_text(msg)
                startup_state.record_message_sent()
                sent_total = startup_state.messages_sent_total()
                if sent_total == 1 or sent_total % 1000 == 0:
                    logger.info("[distributor.ws] sent_total=%s", sent_total)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[distributor.ws] send_error detail=%s", exc)
                startup_state.record_error(f"ws_send_error: {exc}")
                self.disconnect(ws)
                break
