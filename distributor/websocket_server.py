"""FastAPI WebSocket server for the M3 Distribution Layer."""

import logging
import socket
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from agent_007 import Agent007Engine
from agent_007_chat import check_rate_limit, run_agent007_chat
from config import AGENT007_WEIS_MODE
from connection_manager import ConnectionManager
from zmq_consumer import ZmqConsumer

logger = logging.getLogger(__name__)

# TCP engine SWITCH: ver ../docs/PORTS.md
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


# Shared state - initialized in main.py
manager: Optional[ConnectionManager] = None
zmq_consumer: Optional[ZmqConsumer] = None
agent007_engine: Optional[Agent007Engine] = None


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def init_app(
    connection_manager: ConnectionManager,
    consumer: ZmqConsumer,
    agent007: Optional[Agent007Engine] = None,
) -> None:
    """Initialize app with shared components (called from main.py)."""
    global manager, zmq_consumer, agent007_engine
    manager = connection_manager
    zmq_consumer = consumer
    agent007_engine = agent007


def create_app(
    lifespan_context: Any = None,
) -> FastAPI:
    """Create FastAPI app with optional lifespan (startup/shutdown)."""
    app = FastAPI(
        title="M3 Distribution Layer",
        version="1.0.0",
        lifespan=lifespan_context if lifespan_context is not None else _noop_lifespan,
    )

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

    class ChatMessage(BaseModel):
        role: str
        content: str

    class Agent007ChatBody(BaseModel):
        messages: List[ChatMessage] = Field(default_factory=list)

    class Agent007WeisBody(BaseModel):
        side: str  # buy | sell | unknown

    @app.get("/api/agent007/snapshot")
    async def agent007_snapshot() -> dict:
        if agent007_engine is None:
            return {"error": "Agent007 não inicializado"}
        return agent007_engine.get_snapshot()

    @app.post("/api/agent007/chat")
    async def agent007_chat(body: Agent007ChatBody, request: Request) -> dict:
        if agent007_engine is None:
            return {"ok": False, "error": "Agent007 não inicializado"}
        client = request.client.host if request.client else "default"
        ok_rl, msg_rl = check_rate_limit(client)
        if not ok_rl:
            return {"ok": False, "error": msg_rl}
        snap = agent007_engine.get_snapshot()
        user_msgs = [m.model_dump() for m in body.messages]
        ok, text = run_agent007_chat(user_msgs, snap)
        if not ok:
            return {"ok": False, "error": text}
        return {"ok": True, "reply": text}

    @app.post("/api/agent007/weis")
    async def agent007_weis(body: Agent007WeisBody) -> dict:
        if agent007_engine is None:
            return {"ok": False, "error": "Agent007 não inicializado"}
        if AGENT007_WEIS_MODE != "manual":
            return {
                "ok": False,
                "error": "Defina AGENT007_WEIS_MODE=manual no distributor para usar Weis manual.",
            }
        s = (body.side or "").strip().lower()
        if s not in ("buy", "sell", "unknown"):
            return {"ok": False, "error": "side deve ser buy, sell ou unknown"}
        agent007_engine.set_manual_weis(s)
        return {"ok": True, "side": s}

    return app


# For backwards compatibility (e.g. tests that import app)
app = create_app()
