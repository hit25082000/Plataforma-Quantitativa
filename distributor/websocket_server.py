"""FastAPI WebSocket server for the M3 Distribution Layer."""

import logging
import socket
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from connection_manager import ConnectionManager
from zmq_consumer import ZmqConsumer

logger = logging.getLogger(__name__)

ENGINE_CONTROL_PORT = 5556
CONNECT_TIMEOUT_S = 2
RECV_TIMEOUT_S = 15  # engine can take up to 10s to complete SWITCH


def _exchange_to_bolsa(exchange: str) -> str:
    ex = (exchange or "").strip().upper()
    if ex == "BMF":
        return "F"
    if ex == "BOVESPA":
        return "B"
    if ex == "SIM":
        return "SIM"
    return "F"


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


class SetActiveAssetBody(BaseModel):
    ticker: str
    exchange: str


@app.post("/api/set-active-asset")
async def set_active_asset(body: SetActiveAssetBody) -> dict:
    """Envia comando SWITCH ao engine na porta 5556. Usado pelo frontend no browser (sem Tauri)."""
    ticker = (body.ticker or "").strip().upper() or "WINFUT"
    bolsa = _exchange_to_bolsa(body.exchange)
    cmd = f"SWITCH\t{ticker}\t{bolsa}\n"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(CONNECT_TIMEOUT_S)
        s.connect(("127.0.0.1", ENGINE_CONTROL_PORT))
        s.settimeout(RECV_TIMEOUT_S)
        s.sendall(cmd.encode())
        buf = s.recv(256).decode(errors="replace").strip()
        success = buf.startswith("OK")
        return {"success": success, "message": buf if buf else "OK" if success else "No response"}
    except socket.timeout:
        msg = f"Engine não respondeu a tempo (timeout {RECV_TIMEOUT_S}s)."
        return {"success": False, "message": msg}
    except ConnectionRefusedError as e:
        msg = f"Engine não está escutando na porta {ENGINE_CONTROL_PORT}. Reinicie o engine. ({e})"
        return {"success": False, "message": msg}
    except OSError as e:
        msg = str(e)
        if "5556" not in msg and "refused" not in msg.lower() and "escutando" not in msg.lower():
            msg = f"Engine não está escutando na porta {ENGINE_CONTROL_PORT}. ({e})"
        return {"success": False, "message": msg}
    finally:
        try:
            s.close()
        except Exception:
            pass
