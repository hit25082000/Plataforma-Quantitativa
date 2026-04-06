"""FastAPI WebSocket server for the M3 Distribution Layer."""

import logging
import socket
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Optional, cast

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_007 import Agent007Engine
from agent_007_chat import check_rate_limit, run_agent007_chat
from config import AGENT007_WEIS_MODE
from connection_manager import ConnectionManager
from message_router import MessageRouter
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
zmq_consumer_sync: Optional[ZmqConsumer] = None
agent007_engine: Optional[Agent007Engine] = None
message_router: Optional[MessageRouter] = None
market_queue: Optional[Any] = None  # asyncio.Queue[str]; evita import circular


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def init_app(
    connection_manager: ConnectionManager,
    consumer: ZmqConsumer,
    agent007: Optional[Agent007Engine] = None,
    router: Optional[MessageRouter] = None,
    *,
    sync_consumer: Optional[ZmqConsumer] = None,
    market_queue_ref: Optional[Any] = None,
) -> None:
    """Initialize app with shared components (called from main.py)."""
    global manager, zmq_consumer, zmq_consumer_sync, agent007_engine, message_router, market_queue
    manager = connection_manager
    zmq_consumer = consumer
    zmq_consumer_sync = sync_consumer
    agent007_engine = agent007
    message_router = router
    market_queue = market_queue_ref


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
        """Health check: liveness + métricas do pipeline quando inicializado via main."""
        out: dict[str, Any] = {
            "status": "ok",
            "clients": len(manager.active) if manager else 0,
            "zmq": zmq_consumer.is_alive() if zmq_consumer else False,
        }
        if zmq_consumer_sync is not None:
            out["zmq_sync"] = zmq_consumer_sync.is_alive()
        if market_queue is not None:
            q = market_queue
            out["backlog"] = int(cast(Any, q).qsize())
            out["queue_maxsize"] = int(
                getattr(cast(Any, q), "maxsize", 0) or 0
            )
        if message_router is not None:
            r = message_router.metrics()
            out["route_avg_ms"] = float(r["route_avg_ms"])
            out["route_total"] = int(r["route_count_total"])
            out["throttled_dom"] = int(r["throttled_dom_count"])
            out["invalid_json"] = int(r["invalid_json_count"])
        if zmq_consumer is not None:
            out["zmq_metrics_main"] = zmq_consumer.metrics()
        if zmq_consumer_sync is not None:
            out["zmq_metrics_sync"] = zmq_consumer_sync.metrics()
        if zmq_consumer is not None and zmq_consumer_sync is not None:
            m_main = zmq_consumer.metrics()
            m_sync = zmq_consumer_sync.metrics()
            out["dropped_dom_total"] = int(
                m_main["dropped_dom"] + m_sync["dropped_dom"]
            )
            out["rescued_trade_like_total"] = int(
                m_main["rescued_trade_like"] + m_sync["rescued_trade_like"]
            )
        return out

    @app.get("/api/warm-macd")
    async def warm_macd(ticker: str = "WINFUT") -> Any:
        """Último MACD/IFR a partir de estado persistido + CSV (útil ao abrir o app sem trade imediato)."""
        if message_router is None:
            return JSONResponse(
                {"detail": "router not initialized"},
                status_code=503,
            )
        t = (ticker or "WINFUT").strip().upper() or "WINFUT"
        snap = message_router.warm_macd_snapshot(t)
        if snap is None:
            return JSONResponse(
                {"detail": "insufficient_data"},
                status_code=404,
            )
        return snap

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

    class SetRenkoBrickBody(BaseModel):
        """`series` tem prioridade. Compat: só `brick_points` (16 ou 42)."""

        series: Optional[str] = None
        brick_points: Optional[float] = None

    @app.post("/api/set-renko-brick")
    async def set_renko_brick(body: SetRenkoBrickBody) -> dict:
        """Define série do IFR: Renko 42r/16r ou candle 30m (macd_signal)."""
        if message_router is None:
            return {"success": False, "message": "Router não inicializado"}
        raw = (body.series or "").strip().lower() if body.series is not None else ""
        if raw:
            message_router.set_ifr_series(raw)
            if raw in ("30m", "30min", "30_min", "30_minutos", "30 min", "30minutos"):
                return {
                    "success": True,
                    "message": "IFR em candles de 30 minutos",
                    "series": "30m",
                    "brick_points": None,
                }
            bp = 16 if raw.startswith("16") else 42
            return {
                "success": True,
                "message": f"Renko {bp}R ativo",
                "series": f"{bp}r",
                "brick_points": bp,
            }
        if body.brick_points is not None:
            pts = float(body.brick_points)
            if pts not in (16.0, 42.0):
                return {"success": False, "message": "brick_points deve ser 16 ou 42"}
            message_router.set_renko_brick_points(pts)
            return {
                "success": True,
                "message": f"Renko {int(pts)}R ativo",
                "series": f"{int(pts)}r",
                "brick_points": int(pts),
            }
        return {
            "success": False,
            "message": "Informe series (42r, 16r ou 30m) ou brick_points (16 ou 42)",
        }

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
