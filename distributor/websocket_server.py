"""FastAPI WebSocket server for the M3 Distribution Layer."""

import asyncio
import json
import logging
import socket
import uuid
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Optional, Protocol, cast

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_007 import Agent007Engine
from agent_007_chat import chat_metrics, check_rate_limit, run_agent007_chat
from config import AGENT007_WEIS_MODE, GEMINI_LIVE_MODEL, GOOGLE_API_KEY, VOICE_FUNCTIONS_ENABLED, VOICE_SESSION_MAX_DURATION_S, WS_PORT
from connection_manager import ConnectionManager
from message_router import MessageRouter
from security_audit import security_audit_metrics
from voice_realtime import create_realtime_session, execute_function_call, voice_metrics

if TYPE_CHECKING:
    from realtime_rag import RealtimeRagEngine

logger = logging.getLogger(__name__)

# TCP engine SWITCH: ver ../docs/PORTS.md
ENGINE_CONTROL_PORT = 5556
CONNECT_TIMEOUT_S = 3
RECV_TIMEOUT_S = 90  # SWITCH pode aguardar retries + recuperação de sessão no engine


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
zmq_consumer: Optional["ConsumerLike"] = None
zmq_consumer_sync: Optional["ConsumerLike"] = None
agent007_engine: Optional[Agent007Engine] = None
message_router: Optional[MessageRouter] = None
market_queue: Optional[Any] = None  # asyncio.Queue[str]; evita import circular
ipc_mode: str = "zmq"
ipc_fallback_event: Optional[dict[str, Any]] = None
rag_engine: Optional["RealtimeRagEngine"] = None
voice_session_store: dict[str, dict[str, Any]] = {}


class ConsumerLike(Protocol):
    def is_alive(self) -> bool: ...

    def metrics(self) -> dict[str, int]: ...


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def init_app(
    connection_manager: ConnectionManager,
    consumer: ConsumerLike,
    agent007: Optional[Agent007Engine] = None,
    router: Optional[MessageRouter] = None,
    *,
    rag_pipeline: Optional["RealtimeRagEngine"] = None,
    sync_consumer: Optional[ConsumerLike] = None,
    market_queue_ref: Optional[Any] = None,
    market_ipc_mode: str = "zmq",
    fallback_event: Optional[dict[str, Any]] = None,
) -> None:
    """Initialize app with shared components (called from main.py)."""
    global manager, zmq_consumer, zmq_consumer_sync, agent007_engine, message_router, market_queue, ipc_mode, ipc_fallback_event, rag_engine
    manager = connection_manager
    zmq_consumer = consumer
    zmq_consumer_sync = sync_consumer
    agent007_engine = agent007
    message_router = router
    rag_engine = rag_pipeline
    market_queue = market_queue_ref
    ipc_mode = market_ipc_mode
    ipc_fallback_event = fallback_event


def create_app(
    lifespan_context: Any = None,
) -> FastAPI:
    """Create FastAPI app with optional lifespan (startup/shutdown)."""
    app = FastAPI(
        title="M3 Distribution Layer",
        version="1.0.0",
        lifespan=lifespan_context if lifespan_context is not None else _noop_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.websocket("/api/voice/ws/{session_id}")
    async def voice_ws_proxy(websocket: WebSocket, session_id: str) -> None:
        """Proxy local do copiloto de voz para a Gemini Live API."""
        session = voice_session_store.get(session_id)
        if session is None:
            await websocket.close(code=1008, reason="Sessão de voz inválida")
            return

        await websocket.accept()
        voice_session_store.pop(session_id, None)

        upstream = None
        try:
            import websockets

            async with websockets.connect(session["ws_url"], max_size=2**24) as upstream:
                await upstream.send(json.dumps(session["setup_message"]))

                async def forward_upstream() -> None:
                    while True:
                        msg = await upstream.recv()
                        if isinstance(msg, bytes):
                            msg = msg.decode("utf-8", errors="replace")
                        await websocket.send_text(msg)

                async def forward_downstream() -> None:
                    while True:
                        text = await websocket.receive_text()
                        await upstream.send(text)

                tasks = {
                    asyncio.create_task(forward_upstream()),
                    asyncio.create_task(forward_downstream()),
                }
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Voice proxy failed for session %s: %s", session_id, exc)
            with suppress(Exception):
                await websocket.close(code=1011, reason=str(exc)[:120])

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint - accepts connections and keeps them alive."""
        if manager is None:
            await websocket.close(code=1011, reason="Server not initialized")
            return

        await manager.connect(websocket)
        if ipc_fallback_event is not None:
            await websocket.send_text(json.dumps(ipc_fallback_event))
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
            "ipc_mode": ipc_mode,
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
            out["consumer_metrics_main"] = zmq_consumer.metrics()
            out["zmq_metrics_main"] = zmq_consumer.metrics()
        if zmq_consumer_sync is not None:
            out["consumer_metrics_sync"] = zmq_consumer_sync.metrics()
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
            out["gap_count_total"] = int(
                int(m_main.get("gap_count", 0)) + int(m_sync.get("gap_count", 0))
            )
            out["gap_messages_total"] = int(
                int(m_main.get("gap_messages", 0)) + int(m_sync.get("gap_messages", 0))
            )
            out["ring_dropped_total"] = int(
                int(m_main.get("ring_dropped", 0)) + int(m_sync.get("ring_dropped", 0))
            )
            out["integrity_failures_total"] = int(
                int(m_main.get("integrity_failures", 0)) + int(m_sync.get("integrity_failures", 0))
            )
            out["crc_mismatch_total"] = int(
                int(m_main.get("crc_mismatch", 0)) + int(m_sync.get("crc_mismatch", 0))
            )
            out["payload_mismatch_total"] = int(
                int(m_main.get("payload_mismatch", 0)) + int(m_sync.get("payload_mismatch", 0))
            )
            out["committed_mismatch_total"] = int(
                int(m_main.get("committed_mismatch", 0)) + int(m_sync.get("committed_mismatch", 0))
            )
        if ipc_fallback_event is not None:
            out["ipc_fallback"] = ipc_fallback_event
        out["agent007_chat_metrics"] = chat_metrics()
        out["security_audit_metrics"] = security_audit_metrics()
        if rag_engine is not None:
            out["rag_metrics"] = rag_engine.metrics()
        return out

    @app.get("/ipc-state")
    async def ipc_state() -> dict[str, Any]:
        return {
            "ipc_mode": ipc_mode,
            "ipc_fallback": ipc_fallback_event,
        }

    @app.get("/api/warm-macd")
    async def warm_macd(ticker: str = "WINFUT", series: Optional[str] = None) -> Any:
        """Último MACD/IFR a partir de estado persistido + CSV (útil ao abrir o app sem trade imediato)."""
        no_store_headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        if message_router is None:
            return JSONResponse(
                {"detail": "router not initialized"},
                status_code=503,
                headers=no_store_headers,
            )
        t = (ticker or "WINFUT").strip().upper() or "WINFUT"
        s = (series or "").strip()
        if s:
            message_router.set_ifr_series(s)
        snap = message_router.warm_macd_snapshot(t)
        if snap is None:
            return JSONResponse(
                {"detail": "insufficient_data"},
                status_code=404,
                headers=no_store_headers,
            )
        return JSONResponse(snap, headers=no_store_headers)

    class SetActiveAssetBody(BaseModel):
        ticker: str
        exchange: str

    @app.post("/api/set-active-asset")
    async def set_active_asset(body: SetActiveAssetBody) -> dict:
        """Envia comando SWITCH ao engine na porta 5556. Usado pelo frontend no browser (sem Tauri)."""
        ticker = (body.ticker or "").strip().upper() or "WINFUT"
        exchange = (body.exchange or "").strip().upper()
        if ticker == "TESTE":
            exchange = "SIM"
        elif not exchange or exchange == "SIM":
            exchange = "BMF"
        bolsa = _exchange_to_bolsa(exchange)
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
        rag_context = ""
        rag_hits = 0
        if rag_engine is not None and user_msgs:
            query = ""
            for m in reversed(user_msgs):
                if m.get("role") == "user" and (m.get("content") or "").strip():
                    query = (m.get("content") or "").strip()
                    break
            if query:
                rag_data = rag_engine.build_context_for_query(query, snap)
                rag_context = str(rag_data.get("context") or "")
                rag_hits = len(rag_data.get("results") or [])

        ok, text = run_agent007_chat(user_msgs, snap, rag_context=rag_context)
        if not ok:
            return {"ok": False, "error": text}
        return {"ok": True, "reply": text, "rag_hits": rag_hits}

    @app.get("/api/rag/status")
    async def rag_status() -> dict:
        if rag_engine is None:
            return {
                "enabled": False,
                "message": "RAG desabilitado (defina RAG_ENABLED=1).",
            }
        return rag_engine.status()

    @app.get("/api/rag/views")
    async def rag_views(ticker: str = "GLOBAL", lookback_seconds: Optional[int] = None) -> dict[str, Any]:
        if rag_engine is None:
            return {
                "enabled": False,
                "message": "RAG desabilitado (defina RAG_ENABLED=1).",
            }
        tk = (ticker or "GLOBAL").strip().upper() or "GLOBAL"
        lb = lookback_seconds if lookback_seconds is None else max(30, int(lookback_seconds))
        return rag_engine.materialized_view(ticker=tk, lookback_seconds=lb)

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

    # -----------------------------------------------------------------------
    # M8 — Copiloto IA Conversacional: endpoints de voz
    # -----------------------------------------------------------------------

    @app.post("/api/voice/session")
    async def voice_session(request: Request) -> dict:
        """Cria sessão WebRTC na OpenAI Realtime API e devolve o client_secret.

        O frontend usa o client_secret para abrir o canal WebRTC diretamente
        com a Realtime API — hoje o distributor faz proxy local do websocket
        para evitar bloqueios do webview no handshake externo.
        Apenas conexões localhost são permitidas.
        """
        # Restringir a localhost para não expor a chave
        client_host = (request.client.host if request.client else "") or ""
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient", "testserver", ""):
            return JSONResponse(
                {"ok": False, "error": "Acesso restrito a localhost."},
                status_code=403,
            )
        result = create_realtime_session()
        if not result.get("ok"):
            return JSONResponse(result, status_code=503)
        session_id = uuid.uuid4().hex
        voice_session_store[session_id] = {
            "ws_url": result["ws_url"],
            "setup_message": result["setup_message"],
        }
        local_ws_url = f"ws://127.0.0.1:{WS_PORT}/api/voice/ws/{session_id}"
        return {
            **result,
            "ws_url": local_ws_url,
            "session_id": session_id,
            "transport": "proxy",
        }

    class FunctionCallBody(BaseModel):
        function_name: str
        call_id: str = ""

    @app.post("/api/voice/function-call")
    async def voice_function_call(body: FunctionCallBody) -> dict:
        """Executa uma função de mercado invocada pela IA via Data Channel.

        A IA envia o nome da função ao frontend via RTCDataChannel;
        o frontend faz POST aqui e devolve o resultado ao Data Channel.
        """
        if not VOICE_FUNCTIONS_ENABLED:
            return {"ok": False, "error": "Copiloto de voz desabilitado."}
        if agent007_engine is None:
            return {"ok": False, "error": "Agent007 não inicializado."}

        snap = agent007_engine.get_snapshot()

        # Muralhas ativas: extraídas do message_router (DOM state)
        walls: list[Any] = []
        if message_router is not None:
            router_state = getattr(message_router, "get_wall_state", None)
            if callable(router_state):
                walls = router_state()

        result = execute_function_call(
            function_name=body.function_name,
            agent007_snapshot=snap,
            active_walls=walls,
        )
        return {"ok": True, "call_id": body.call_id, "result": result}

    @app.get("/api/voice/status")
    async def voice_status() -> dict:
        """Retorna estado do copiloto de voz: feature flag + métricas de sessões."""
        return {
            "enabled": VOICE_FUNCTIONS_ENABLED,
            "api_key_configured": bool(GOOGLE_API_KEY),
            "provider": "gemini",
            "model": GEMINI_LIVE_MODEL,
            "max_session_duration_s": VOICE_SESSION_MAX_DURATION_S,
            "voice_metrics": voice_metrics(),
        }

    return app


# For backwards compatibility (e.g. tests that import app)
app = create_app()
