"""FastAPI WebSocket server for the M3 Distribution Layer."""

import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from connection_manager import ConnectionManager
from zmq_consumer import ZmqConsumer

logger = logging.getLogger(__name__)

app = FastAPI(title="M3 Distribution Layer", version="1.0.0")

# Shared state - initialized in main.py
manager: Optional[ConnectionManager] = None
zmq_consumer: Optional[ZmqConsumer] = None


def init_app(
    connection_manager: ConnectionManager,
    consumer: ZmqConsumer,
) -> None:
    """Initialize app with shared components (called from main.py)."""
    global manager, zmq_consumer
    manager = connection_manager
    zmq_consumer = consumer


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint - accepts connections and keeps them alive."""
    if manager is None:
        await websocket.close(code=1011, reason="Server not initialized")
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # mantém conexão viva (ignora input do cliente)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/health")
async def health() -> dict:
    """Health check with client count and ZMQ consumer status."""
    return {
        "status": "ok",
        "clients": len(manager.active) if manager else 0,
        "zmq": zmq_consumer.is_alive() if zmq_consumer else False,
    }
