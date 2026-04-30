"""FastAPI WebSocket server for the M3 Distribution Layer."""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Optional, Protocol, cast

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_007 import Agent007Engine
from agent_007_chat import chat_metrics, check_rate_limit, run_agent007_chat
from config import AGENT007_WEIS_MODE, GEMINI_LIVE_MODEL, GOOGLE_API_KEY, VOICE_FUNCTIONS_ENABLED, VOICE_SESSION_MAX_DURATION_S, WS_PORT
from connection_manager import ConnectionManager
from message_router import MessageRouter
from message_router import canonical_symbol
from vp_ocr_enrich import enrich_vp_overlay_payload
from security_audit import security_audit_metrics
from voice_realtime import create_realtime_session, execute_function_call, voice_metrics

if TYPE_CHECKING:
    from realtime_rag import RealtimeRagEngine

logger = logging.getLogger(__name__)
STARTED_AT = time.time()
BUILD_TAG = "vp-runtime-debug-2026-04-27"
OCR_OVERLAY_PORT = int(os.environ.get("PQ_OCR_PORT", "5558"))

# TCP engine SWITCH: ver ../docs/PORTS.md
ENGINE_CONTROL_PORT = 5556
CONNECT_TIMEOUT_S = 3
RECV_TIMEOUT_S = 90  # SWITCH pode aguardar retries + recuperação de sessão no engine


def _ocr_error_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sanitize_error_details(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        compact = " ".join(raw.split())
        return compact[:300] + ("..." if len(compact) > 300 else "")
    if isinstance(raw, dict):
        allowed = {
            "error",
            "message",
            "reason",
            "status",
            "code",
            "detail",
            "details",
            "fields",
            "field",
            "required",
            "min",
            "max",
            "value",
        }
        sanitized: dict[str, Any] = {}
        for key in allowed:
            if key in raw:
                sanitized[key] = _sanitize_error_details(raw.get(key))
        return sanitized or {"message": "downstream_error"}
    if isinstance(raw, list):
        return [_sanitize_error_details(item) for item in raw[:5]]
    return _sanitize_error_details(str(raw))


def _ocr_error_response(
    *,
    status_code: int,
    endpoint: str,
    error_code: str,
    message: str,
    details: Any = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "endpoint": endpoint,
            "error_code": error_code,
            "message": message,
            "ts": _ocr_error_ts(),
            "details": _sanitize_error_details(details),
        },
    )


def _exchange_to_bolsa(exchange: str) -> str:
    ex = (exchange or "").strip().upper()
    if ex == "BMF":
        return "F"
    if ex == "BOVESPA":
        return "B"
    if ex == "SIM":
        return "SIM"
    return "F"


def _ocr_overlay_url(path: str) -> str:
    return f"http://127.0.0.1:{OCR_OVERLAY_PORT}{path}"


_OCR_CONFIG_LIMITS: dict[str, tuple[float, float]] = {
    "refresh_ms": (120.0, 800.0),
    "ws_publish_min_ms": (100.0, 2000.0),
    "axis_max_bad_frames": (1.0, 120.0),
    "line_y_smooth_alpha": (0.0, 1.0),
    "line_y_snap_px": (1.0, 200.0),
    "line_y_deadband_px": (0.0, 20.0),
    "axis_blend_beta": (0.01, 1.0),
    "axis_warmup_secs": (0.0, 120.0),
    "min_conf": (0.0, 100.0),
}

_OCR_CONFIG_ALLOWED_FIELDS = set(_OCR_CONFIG_LIMITS)
_OCR_CONFIG_INT_FIELDS = {
    "refresh_ms",
    "ws_publish_min_ms",
    "axis_max_bad_frames",
    "min_conf",
}


def _validate_ocr_overlay_config_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _ocr_error_response(
            status_code=400,
            endpoint="/api/ocr-overlay/config",
            error_code="OCR_INVALID_PAYLOAD",
            message="Payload inválido para configuração do OCR overlay.",
            details={"reason": "payload_must_be_object"},
        )
    if not payload:
        raise _ocr_error_response(
            status_code=400,
            endpoint="/api/ocr-overlay/config",
            error_code="OCR_INVALID_PAYLOAD",
            message="Payload inválido para configuração do OCR overlay.",
            details={"reason": "payload_must_not_be_empty"},
        )
    unknown_fields = sorted(str(k) for k in payload if str(k) not in _OCR_CONFIG_ALLOWED_FIELDS)
    if unknown_fields:
        raise _ocr_error_response(
            status_code=400,
            endpoint="/api/ocr-overlay/config",
            error_code="OCR_INVALID_PAYLOAD",
            message="Payload inválido para configuração do OCR overlay.",
            details={"reason": "unknown_fields", "fields": unknown_fields},
        )

    normalized: dict[str, Any] = {}
    invalid_fields: list[dict[str, Any]] = []
    for field, value in payload.items():
        name = str(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid_fields.append({"field": name, "reason": "must_be_number"})
            continue
        num_value = float(value)
        min_value, max_value = _OCR_CONFIG_LIMITS[name]
        if num_value < min_value or num_value > max_value:
            invalid_fields.append(
                {
                    "field": name,
                    "reason": "out_of_range",
                    "min": min_value,
                    "max": max_value,
                    "value": num_value,
                }
            )
            continue
        if name in _OCR_CONFIG_INT_FIELDS:
            normalized[name] = int(round(num_value))
        else:
            normalized[name] = num_value

    if invalid_fields:
        raise _ocr_error_response(
            status_code=400,
            endpoint="/api/ocr-overlay/config",
            error_code="OCR_INVALID_PAYLOAD",
            message="Payload inválido para configuração do OCR overlay.",
            details={"reason": "invalid_fields", "fields": invalid_fields},
        )
    return normalized


def _ocr_overlay_proxy_sync(method: str, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    data_bytes = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        _ocr_overlay_url(path),
        data=data_bytes,
        headers=headers,
        method=method.upper(),
    )
    with urllib.request.urlopen(req, timeout=4.0) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {"ok": True}


async def _ocr_overlay_proxy(method: str, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    endpoint = f"/api/ocr-overlay{path.removeprefix('/api/ocr-overlay')}"
    try:
        response = await asyncio.to_thread(_ocr_overlay_proxy_sync, method, path, payload)
        if not isinstance(response, dict):
            raise _ocr_error_response(
                status_code=503,
                endpoint=endpoint,
                error_code="OCR_DOWNSTREAM_BAD_PAYLOAD",
                message="Resposta inválida do serviço OCR overlay.",
                details={"type": str(type(response))},
            )
        if response.get("ok") is False:
            raise _ocr_error_response(
                status_code=503,
                endpoint=endpoint,
                error_code="OCR_DEGRADED_STATE",
                message="Serviço OCR overlay em estado degradado.",
                details={
                    "downstream_endpoint": response.get("endpoint"),
                    "error": response.get("error"),
                    "meta": response.get("meta"),
                },
            )
        return response
    except urllib.error.HTTPError as exc:
        detail_bytes = b""
        with suppress(Exception):
            detail_bytes = exc.read()
        detail = detail_bytes.decode("utf-8", errors="replace") if detail_bytes else ""
        parsed_detail: Any = detail
        try:
            parsed_detail = json.loads(detail)
        except Exception:  # noqa: BLE001
            parsed_detail = detail
        if exc.code in (400, 422):
            raise _ocr_error_response(
                status_code=400,
                endpoint=endpoint,
                error_code="OCR_INVALID_PAYLOAD",
                message="Payload inválido para OCR overlay.",
                details=parsed_detail,
            ) from exc
        if exc.code == 409:
            raise _ocr_error_response(
                status_code=409,
                endpoint=endpoint,
                error_code="OCR_INCONSISTENT_STATE",
                message="Estado inconsistente no OCR overlay.",
                details=parsed_detail,
            ) from exc
        if exc.code in (408, 504):
            raise _ocr_error_response(
                status_code=504,
                endpoint=endpoint,
                error_code="OCR_DOWNSTREAM_TIMEOUT",
                message="Timeout no serviço OCR overlay.",
                details=parsed_detail,
            ) from exc
        raise _ocr_error_response(
            status_code=503,
            endpoint=endpoint,
            error_code="OCR_DOWNSTREAM_UNAVAILABLE",
            message=f"Serviço OCR overlay indisponível ({exc.code}).",
            details=parsed_detail,
        ) from exc
    except TimeoutError as exc:
        raise _ocr_error_response(
            status_code=504,
            endpoint=endpoint,
            error_code="OCR_DOWNSTREAM_TIMEOUT",
            message="Timeout no serviço OCR overlay.",
            details=str(exc),
        ) from exc
    except socket.timeout as exc:
        raise _ocr_error_response(
            status_code=504,
            endpoint=endpoint,
            error_code="OCR_DOWNSTREAM_TIMEOUT",
            message="Timeout no serviço OCR overlay.",
            details=str(exc),
        ) from exc
    except json.JSONDecodeError as exc:
        raise _ocr_error_response(
            status_code=503,
            endpoint=endpoint,
            error_code="OCR_DOWNSTREAM_BAD_PAYLOAD",
            message="Resposta inválida do serviço OCR overlay.",
            details=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _ocr_error_response(
            status_code=503,
            endpoint=endpoint,
            error_code="OCR_DOWNSTREAM_UNAVAILABLE",
            message="Serviço OCR overlay indisponível.",
            details=str(exc),
        ) from exc


# Shared state - initialized in main.py
manager: Optional[ConnectionManager] = None
vp_tape_manager: Optional[ConnectionManager] = None
vp_overlay_manager: Optional[ConnectionManager] = None
zmq_consumer: Optional["ConsumerLike"] = None
zmq_consumer_sync: Optional["ConsumerLike"] = None
zmq_consumer_market_aux: Optional["ConsumerLike"] = None
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


class VpSatoDemoRequest(BaseModel):
    ticker: str = Field(default="DEMO")
    base_price: float = Field(default=100000.0)
    price_step: float = Field(default=5.0, gt=0)
    levels: int = Field(default=72, ge=20, le=180)
    seed: int = Field(default=0)


def _value_area_bounds(levels: list[dict[str, Any]], poc_index: int) -> tuple[float, float]:
    target = sum(float(row["total_vol"]) for row in levels) * 0.70
    total = float(levels[poc_index]["total_vol"])
    lo = hi = poc_index
    while total < target and (lo > 0 or hi < len(levels) - 1):
        down = float(levels[lo - 1]["total_vol"]) if lo > 0 else -1.0
        up = float(levels[hi + 1]["total_vol"]) if hi < len(levels) - 1 else -1.0
        if up >= down and hi < len(levels) - 1:
            hi += 1
            total += float(levels[hi]["total_vol"])
        elif lo > 0:
            lo -= 1
            total += float(levels[lo]["total_vol"])
        else:
            break
    return float(levels[hi]["price"]), float(levels[lo]["price"])


def _build_vp_sato_demo_messages(req: VpSatoDemoRequest) -> list[dict[str, Any]]:
    import math

    count = int(req.levels)
    center = count // 2
    drift = (int(req.seed) % 9) - 4
    main_center = center + drift
    upper_center = max(0, min(count - 1, center - 18 + drift // 2))
    lower_center = max(0, min(count - 1, center + 16 - drift // 2))
    levels: list[dict[str, Any]] = []
    for i in range(count):
        price = float(req.base_price + (center - i) * req.price_step)
        main = 920.0 * math.exp(-((i - main_center) ** 2) / (2 * 8.0**2))
        upper = 310.0 * math.exp(-((i - upper_center) ** 2) / (2 * 5.0**2))
        lower = 420.0 * math.exp(-((i - lower_center) ** 2) / (2 * 6.0**2))
        wave = 45.0 * (1.0 + math.sin((i + req.seed) * 0.83))
        total = int(max(8.0, main + upper + lower + wave))
        ask_share = 0.58 if i < main_center else 0.42
        ask = int(total * ask_share)
        bid = total - ask
        levels.append(
            {
                "price": price,
                "total_vol": total,
                "bid_vol": bid,
                "ask_vol": ask,
                "pct_of_max": 0.0,
            }
        )
    max_vol = max(int(row["total_vol"]) for row in levels)
    for row in levels:
        row["pct_of_max"] = round(float(row["total_vol"]) / max_vol, 6)
    poc_index = max(range(len(levels)), key=lambda idx: (levels[idx]["total_vol"], levels[idx]["price"]))
    poc = float(levels[poc_index]["price"])
    vah, val = _value_area_bounds(levels, poc_index)
    total_vol = int(sum(int(row["total_vol"]) for row in levels))
    ts = int(time.time() * 1000)
    vp = {
        "topic": "market",
        "type": "volume_profile",
        "ticker": req.ticker.strip().upper() or "DEMO",
        "period": "manual",
        "timestamp": ts,
        "price_step": float(req.price_step),
        "total_vol": total_vol,
        "poc": poc,
        "vah": vah,
        "val": val,
        "levels": levels,
        "demo": True,
    }
    top3 = [
        {
            "player": 1000 + i + int(req.seed) % 7,
            "price": poc,
            "total_vol": max(1, int(max_vol * (0.72 - i * 0.16))),
            "bid_vol": max(1, int(max_vol * (0.34 - i * 0.07))),
            "ask_vol": max(1, int(max_vol * (0.38 - i * 0.09))),
            "buy_absorption": max(0, int(max_vol * (0.05 - i * 0.01))),
            "sell_absorption": max(0, int(max_vol * (0.04 - i * 0.01))),
        }
        for i in range(3)
    ]
    tape = {
        "topic": "market",
        "type": "tape_intelligence",
        "ticker": vp["ticker"],
        "timestamp": ts,
        "poc_price": poc,
        "vah_price": vah,
        "val_price": val,
        "poc_player": top3[0]["player"],
        "val_buyer": 1088 + int(req.seed) % 5,
        "vah_seller": 2020 + int(req.seed) % 5,
        "poc_top3": top3,
        "vah_top3": top3,
        "val_top3": top3,
        "val_holder_state": "ok",
        "vah_holder_state": "ok",
        "demo": True,
    }
    return [vp, tape]


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def init_app(
    connection_manager: ConnectionManager,
    consumer: ConsumerLike,
    agent007: Optional[Agent007Engine] = None,
    router: Optional[MessageRouter] = None,
    *,
    volume_profile_connection_manager: Optional[ConnectionManager] = None,
    vp_overlay_connection_manager: Optional[ConnectionManager] = None,
    rag_pipeline: Optional["RealtimeRagEngine"] = None,
    sync_consumer: Optional[ConsumerLike] = None,
    zmq_market_aux: Optional[ConsumerLike] = None,
    market_queue_ref: Optional[Any] = None,
    market_ipc_mode: str = "zmq",
    fallback_event: Optional[dict[str, Any]] = None,
) -> None:
    """Initialize app with shared components (called from main.py)."""
    global manager, vp_tape_manager, vp_overlay_manager, zmq_consumer, zmq_consumer_sync, zmq_consumer_market_aux, agent007_engine, message_router, market_queue, ipc_mode, ipc_fallback_event, rag_engine
    manager = connection_manager
    vp_tape_manager = volume_profile_connection_manager
    vp_overlay_manager = vp_overlay_connection_manager
    zmq_consumer = consumer
    zmq_consumer_sync = sync_consumer
    zmq_consumer_market_aux = zmq_market_aux
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

    @app.websocket("/ws/volume-profile")
    async def ws_volume_profile(websocket: WebSocket) -> None:
        """Apenas snapshots VP e T&T (enriquecidos) — overlay ou clientes leves sem /ws completo."""
        if vp_tape_manager is None:
            await websocket.close(code=1011, reason="Server not initialized")
            return
        symbol = (websocket.query_params.get("symbol") or "WINFUT").strip().upper()
        await vp_tape_manager.connect(websocket)
        if message_router is not None:
            snap = message_router.latest_volume_profile_snapshot(symbol)
            if snap is not None:
                try:
                    await websocket.send_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
                    logger.info(
                        "[VP_WS] client_connected symbol=%s snapshot_total=%s poc=%s",
                        symbol,
                        snap.get("total_vol"),
                        snap.get("poc"),
                    )
                except Exception:
                    pass
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            vp_tape_manager.disconnect(websocket)

    @app.get("/api/volume-profile/debug")
    async def volume_profile_debug(symbol: str = "WINFUT") -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        snap = message_router.latest_volume_profile_snapshot(symbol)
        counters = message_router.debug_counters()
        now = time.time()
        if snap is None:
            return {
                "ok": True,
                "symbol": symbol,
                "has_profile": False,
                "snapshot": None,
                "bins_count": 0,
                "poc": None,
                "vah": None,
                "val": None,
                "total_vol": 0,
                "source": None,
                "updated_at": None,
                "age_sec": None,
                **counters,
            }
        levels = snap.get("levels") or []
        total_vol = snap.get("total_vol") or 0
        updated_at = snap.get("updated_at")
        age_sec = None
        if isinstance(updated_at, (int, float)):
            age_sec = round(max(0.0, now - float(updated_at)), 2)
        return {
            "ok": True,
            "symbol": snap.get("ticker", symbol),
            "has_profile": int(total_vol) > 0,
            "snapshot": snap,
            "bins_count": len(levels) if isinstance(levels, list) else 0,
            "poc": snap.get("poc"),
            "vah": snap.get("vah"),
            "val": snap.get("val"),
            "total_vol": total_vol,
            "raw_symbol": snap.get("raw_ticker"),
            "source": snap.get("source"),
            "updated_at": updated_at,
            "age_sec": age_sec,
            **counters,
        }

    @app.post("/api/volume-profile/debug/inject-trade")
    async def volume_profile_debug_inject_trade() -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        injected = message_router.inject_debug_trade("WINJ26", 125000, 10)
        return {
            "ok": True,
            "injected": {"type": "trade", "ticker": "WINJ26", "price": 125000, "qty": 10},
            "snapshot": message_router.latest_volume_profile_snapshot("WINFUT"),
            "vp_event": injected,
        }

    @app.post("/api/volume-profile/debug/clear")
    async def volume_profile_debug_clear(symbol: str = "WINFUT") -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        canon = canonical_symbol(symbol)
        message_router.clear_volume_profile(canon)
        return {"ok": True, "symbol": canon}

    @app.get("/api/runtime/debug")
    async def runtime_debug() -> dict[str, Any]:
        return {
            "ok": True,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": STARTED_AT,
            "uptime_sec": round(time.time() - STARTED_AT, 2),
            "build_tag": BUILD_TAG,
        }

    @app.get("/api/ocr-overlay/status")
    async def ocr_overlay_status() -> dict[str, Any]:
        return await _ocr_overlay_proxy("GET", "/api/ocr-overlay/status")

    @app.get("/api/ocr-overlay/debug")
    async def ocr_overlay_debug() -> dict[str, Any]:
        return await _ocr_overlay_proxy("GET", "/api/ocr-overlay/debug")

    @app.post("/api/ocr-overlay/recalibrate")
    async def ocr_overlay_recalibrate() -> dict[str, Any]:
        return await _ocr_overlay_proxy("POST", "/api/ocr-overlay/recalibrate")

    @app.post("/api/ocr-overlay/freeze")
    async def ocr_overlay_freeze() -> dict[str, Any]:
        return await _ocr_overlay_proxy("POST", "/api/ocr-overlay/freeze")

    @app.post("/api/ocr-overlay/unfreeze")
    async def ocr_overlay_unfreeze() -> dict[str, Any]:
        return await _ocr_overlay_proxy("POST", "/api/ocr-overlay/unfreeze")

    @app.get("/api/ocr-overlay/config")
    async def ocr_overlay_config() -> dict[str, Any]:
        return await _ocr_overlay_proxy("GET", "/api/ocr-overlay/config")

    @app.post("/api/ocr-overlay/config")
    async def ocr_overlay_config_update(body: dict[str, Any]) -> dict[str, Any]:
        payload = _validate_ocr_overlay_config_payload(body)
        return await _ocr_overlay_proxy("POST", "/api/ocr-overlay/config", payload=payload)

    @app.post("/api/ocr-overlay/manual-calibration")
    async def ocr_overlay_manual_calibration(body: dict[str, Any]) -> dict[str, Any]:
        points = body.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise _ocr_error_response(
                status_code=400,
                endpoint="/api/ocr-overlay/manual-calibration",
                error_code="OCR_INVALID_PAYLOAD",
                message="Payload inválido para calibração manual.",
                details={"required": "points[] com pelo menos 2 itens"},
            )
        return await _ocr_overlay_proxy("POST", "/api/ocr-overlay/manual-calibration", payload=body)

    @app.post("/api/ocr-overlay/manual-unlock")
    async def ocr_overlay_manual_unlock() -> dict[str, Any]:
        return await _ocr_overlay_proxy("POST", "/api/ocr-overlay/manual-unlock")

    @app.websocket("/ws/tape-intelligence")
    async def ws_tape_intelligence(websocket: WebSocket) -> None:
        """Alias dedicado para clientes focados apenas em Tape Intelligence."""
        if vp_tape_manager is None:
            await websocket.close(code=1011, reason="Server not initialized")
            return
        await vp_tape_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            vp_tape_manager.disconnect(websocket)

    @app.websocket("/ws/vp-overlay")
    async def ws_vp_overlay(websocket: WebSocket) -> None:
        if vp_overlay_manager is None:
            await websocket.close(code=1011, reason="Server not initialized")
            return
        symbol = (websocket.query_params.get("symbol") or "WINFUT").strip().upper()
        await vp_overlay_manager.connect(websocket)
        if message_router is not None:
            snap = message_router.vp_overlay_last_snapshot(symbol)
            if snap is not None:
                try:
                    snap_e = await asyncio.to_thread(enrich_vp_overlay_payload, snap)
                    await websocket.send_text(
                        json.dumps(snap_e, ensure_ascii=False, separators=(",", ":"))
                    )
                except Exception:
                    pass
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            vp_overlay_manager.disconnect(websocket)

    @app.get("/api/vp-overlay/debug")
    async def vp_overlay_debug(symbol: str = "WINFUT") -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        raw = message_router.vp_overlay_debug_snapshot(symbol)
        last = raw.get("last_vp_overlay")
        if isinstance(last, dict):
            raw = dict(raw)
            raw["last_vp_overlay"] = await asyncio.to_thread(enrich_vp_overlay_payload, last)
        return raw

    @app.get("/api/vp-overlay/last")
    async def vp_overlay_last(symbol: str = "WINFUT") -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        snap = message_router.vp_overlay_last_snapshot(symbol)
        if isinstance(snap, dict):
            snap = await asyncio.to_thread(enrich_vp_overlay_payload, snap)
        return {"ok": True, "symbol": symbol, "snapshot": snap}

    @app.post("/api/vp-overlay/reset")
    async def vp_overlay_reset(symbol: str = "") -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        message_router.vp_overlay_reset(symbol.strip() or None)
        return {"ok": True, "symbol": symbol or "*"}

    @app.post("/api/vp-overlay/demo")
    async def vp_overlay_demo() -> dict[str, Any]:
        if message_router is None or vp_overlay_manager is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        path = root / "docs" / "contracts" / "fixtures" / "vp-overlay-demo.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        snap = await message_router.vp_overlay_publish_demo_payload(payload)
        return {"ok": True, "injected": snap.get("symbol") if isinstance(snap, dict) else None, "snapshot": snap}

    @app.post("/api/vp-sato/demo")
    async def vp_sato_demo(payload: VpSatoDemoRequest) -> dict[str, Any]:
        if message_router is None:
            raise HTTPException(status_code=503, detail="router not initialized")
        messages = _build_vp_sato_demo_messages(payload)
        for msg in messages:
            await message_router.route(json.dumps(msg, ensure_ascii=False, separators=(",", ":")))
        vp = messages[0]
        return {
            "ok": True,
            "ticker": vp["ticker"],
            "levels": len(vp["levels"]),
            "poc": vp["poc"],
            "vah": vp["vah"],
            "val": vp["val"],
            "total_vol": vp["total_vol"],
        }

    @app.get("/health")
    async def health() -> dict:
        """Health check: liveness + métricas do pipeline quando inicializado via main."""
        out: dict[str, Any] = {
            "status": "ok",
            "clients": len(manager.active) if manager else 0,
            "clients_volume_profile": len(vp_tape_manager.active) if vp_tape_manager else 0,
            "clients_vp_overlay": len(vp_overlay_manager.active) if vp_overlay_manager else 0,
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
            out["ui_aggregated_count"] = int(r.get("ui_aggregated_count", 0))
            out["ui_flushed_count"] = int(r.get("ui_flushed_count", 0))
            out["ui_replaced_count"] = int(r.get("ui_replaced_count", 0))
            out["ui_trade_batched_count"] = int(r.get("ui_trade_batched_count", 0))
            out["ui_skipped_due_no_clients"] = int(r.get("ui_skipped_due_no_clients", 0))
            out["ui_flush_duration_ms"] = float(r.get("ui_flush_duration_ms", 0.0))
            out["ui_flush_loop_lag_ms"] = float(r.get("ui_flush_loop_lag_ms", 0.0))
            dbg = message_router.vp_overlay_debug_snapshot("WINFUT")
            consolidator = dbg.get("consolidator") if isinstance(dbg, dict) else None
            if isinstance(consolidator, dict):
                out["vp_overlay_last_publish_age_ms"] = consolidator.get(
                    "last_overlay_publish_age_ms"
                )
                out["vp_overlay_last_publish_age_sec"] = consolidator.get(
                    "last_overlay_publish_age_sec"
                )
                out["vp_overlay_emit_count"] = consolidator.get("vp_overlay_emit_count")
                out["vp_overlay_skipped_same_hash"] = consolidator.get(
                    "vp_overlay_skipped_same_hash"
                )
                out["vp_overlay_vp_cache_size"] = consolidator.get("vp_cache_size")
                out["vp_overlay_tape_cache_size"] = consolidator.get("tape_cache_size")
        if manager is not None:
            cm = manager.metrics()
            out["connected_ws_clients"] = int(cm.get("connected_ws_clients", 0))
            out["ui_client_queue_dropped"] = int(cm.get("ui_client_queue_dropped", 0))
        if vp_overlay_manager is not None:
            vom = vp_overlay_manager.metrics()
            dk = next((k for k in vom if k.endswith("_queue_dropped")), None)
            if dk:
                out[dk] = int(vom.get(dk, 0))
        if zmq_consumer is not None:
            out["consumer_metrics_main"] = zmq_consumer.metrics()
            out["zmq_metrics_main"] = zmq_consumer.metrics()
        if zmq_consumer_sync is not None:
            out["consumer_metrics_sync"] = zmq_consumer_sync.metrics()
            out["zmq_metrics_sync"] = zmq_consumer_sync.metrics()
        if zmq_consumer_market_aux is not None:
            out["zmq_market_aux"] = zmq_consumer_market_aux.is_alive()
            out["consumer_metrics_market_aux"] = zmq_consumer_market_aux.metrics()
            out["zmq_metrics_market_aux"] = zmq_consumer_market_aux.metrics()
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
