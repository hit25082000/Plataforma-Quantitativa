"""Entry point for M3 Distribution Layer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Optional

import uvicorn

from agent_007 import Agent007Engine
from config import (
    DOM_THROTTLE_MS,
    IPC_MODE,
    MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    MARKET_QUEUE_MAXSIZE,
    SHM_FALLBACK_PROBE_INTERVAL_MS,
    SHM_FALLBACK_PROBE_TIMEOUT_MS,
    SHM_MAPPING_NAME,
    SHM_SIZE_MB,
    UI_CLIENT_QUEUE_MAXSIZE,
    WS_HOST,
    WS_PORT,
    ZMQ_ADDRESS,
    ZMQ_SYNC_ADDRESS,
)
from connection_manager import ConnectionManager
from message_router import MessageRouter
from mmap_consumer import MmapConsumer
from realtime_rag import create_rag_engine_from_config
from startup_state import startup_state
from vp_overlay_consolidator import VpOverlayConsolidator
from websocket_server import create_app, init_app
from zmq_consumer import ZmqConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


try:
    VP_OVERLAY_POSITION_UPDATE_MS = int(os.environ.get("PQ_OVERLAY_POSITION_UPDATE_MS", "500"))
except ValueError:
    VP_OVERLAY_POSITION_UPDATE_MS = 500
VP_OVERLAY_POSITION_UPDATE_MS = max(120, min(2000, VP_OVERLAY_POSITION_UPDATE_MS))


def _ipc_mode_requested() -> str:
    mode = (IPC_MODE or "").strip().lower()
    if mode in ("shm", "zmq"):
        return mode
    return "zmq"


def _ipc_probe_timeout_ms() -> int:
    return max(200, int(SHM_FALLBACK_PROBE_TIMEOUT_MS))


def _log_startup(event: str, **fields: Any) -> None:
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    details = " ".join(f"{k}={_format_value(v)}" for k, v in fields.items())
    if details:
        logger.info("[distributor.%s] %s", event, details)
    else:
        logger.info("[distributor.%s]", event)


def _is_market_event_message(raw: str) -> bool:
    if '"topic":"market"' in raw or '"topic": "market"' in raw:
        return True
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("topic") == "market"


def _market_type_for_log(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "unknown"
    if isinstance(payload, dict):
        return str(payload.get("type", "unknown"))
    return "unknown"


def _attach_task_guard(task: asyncio.Task[Any], *, name: str) -> asyncio.Task[Any]:
    def _on_done(done_task: asyncio.Task[Any]) -> None:
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is None:
            return
        status = "consumer_error" if name in ("consume_loop", "market_consumer_loop") else "error"
        startup_state.set_ready(False)
        startup_state.set_status(status)
        startup_state.set_error(f"{name}_failed: {exc}")
        logger.exception(
            "Background task '%s' failed: %s",
            name,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    task.add_done_callback(_on_done)
    return task


async def consume_loop(queue: asyncio.Queue[str], router: MessageRouter) -> None:
    """Consume messages from queue and route to WebSocket clients."""
    last_log_ms = 0.0
    while True:
        msg = await queue.get()
        is_market_event = _is_market_event_message(msg)
        is_first_market_event = startup_state.record_message_received(
            is_market_event=is_market_event
        )
        if is_first_market_event:
            logger.info(
                "[distributor.consumer] first_event_received type=%s",
                _market_type_for_log(msg),
            )
        try:
            await router.route(msg)
        except Exception as exc:  # noqa: BLE001
            startup_state.record_error(f"consume_loop_route_error: {exc}")
            raise
        now_ms = asyncio.get_running_loop().time() * 1000
        if now_ms - last_log_ms >= 5000:
            backlog = queue.qsize()
            if backlog > 0:
                logger.info("Consume loop backlog=%s messages", backlog)
            last_log_ms = now_ms


@dataclass
class DistributorRuntime:
    queue: asyncio.Queue[str]
    manager: ConnectionManager
    vp_tape_manager: ConnectionManager
    vp_overlay_manager: ConnectionManager
    vp_overlay_consolidator: VpOverlayConsolidator
    agent007_engine: Agent007Engine
    rag_engine: Any
    router: MessageRouter
    consumer: Any = None
    consumer_sync: Optional[ZmqConsumer] = None
    consumer_zmq_market_aux: Optional[ZmqConsumer] = None
    effective_ipc_mode: str = "unknown"
    fallback_event: dict[str, Any] | None = None
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)


def build_runtime() -> DistributorRuntime:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MARKET_QUEUE_MAXSIZE)
    manager = ConnectionManager(client_queue_maxsize=UI_CLIENT_QUEUE_MAXSIZE)
    vp_tape_manager = ConnectionManager(client_queue_maxsize=UI_CLIENT_QUEUE_MAXSIZE)
    vp_overlay_manager = ConnectionManager(
        client_queue_maxsize=1,
        dropped_metric_key="vp_overlay_client_queue_dropped",
    )
    vp_overlay_consolidator = VpOverlayConsolidator(
        publish_interval_ms=VP_OVERLAY_POSITION_UPDATE_MS
    )
    agent007_engine = Agent007Engine()
    rag_engine = create_rag_engine_from_config()
    router = MessageRouter(
        manager,
        DOM_THROTTLE_MS,
        agent007_engine,
        rag_engine=rag_engine,
        vp_tape_manager=vp_tape_manager,
        vp_overlay_manager=vp_overlay_manager,
        vp_overlay_consolidator=vp_overlay_consolidator,
    )
    return DistributorRuntime(
        queue=queue,
        manager=manager,
        vp_tape_manager=vp_tape_manager,
        vp_overlay_manager=vp_overlay_manager,
        vp_overlay_consolidator=vp_overlay_consolidator,
        agent007_engine=agent007_engine,
        rag_engine=rag_engine,
        router=router,
    )


def resolve_market_consumer(queue: asyncio.Queue[str]) -> tuple[Any, str, dict[str, Any] | None]:
    """Build market consumer with one-way startup fallback shm->zmq."""
    requested_mode = _ipc_mode_requested()
    startup_state.set_ipc_mode(requested_mode)
    logger.info(
        "Distributor IPC request: IPC_MODE=%s requested_mode=%s SHM_FALLBACK_PROBE_TIMEOUT_MS=%s",
        os.environ.get("IPC_MODE", ""),
        requested_mode,
        _ipc_probe_timeout_ms(),
    )

    if requested_mode != "shm":
        _log_startup("ipc", mode="zmq", source="default")
        consumer = ZmqConsumer(
            ZMQ_ADDRESS,
            queue,
            dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
        )
        return consumer, "zmq", None

    probe_timeout_ms = _ipc_probe_timeout_ms()
    _log_startup(
        "ipc",
        mode="shm",
        timeout_ms=probe_timeout_ms,
        mapping=SHM_MAPPING_NAME,
        size_mb=SHM_SIZE_MB,
    )
    map_size_bytes = SHM_SIZE_MB * 1024 * 1024
    deadline = time.monotonic() + probe_timeout_ms / 1000.0
    reason = "probe_timeout"

    while time.monotonic() < deadline:
        ok, reason = MmapConsumer.probe_mapping(SHM_MAPPING_NAME, map_size_bytes)
        if ok:
            consumer = MmapConsumer(
                SHM_MAPPING_NAME,
                queue,
                map_size_bytes=map_size_bytes,
                dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
            )
            return consumer, "shm", None
        time.sleep(max(20, SHM_FALLBACK_PROBE_INTERVAL_MS) / 1000.0)

    fallback_event = {
        "topic": "system",
        "type": "ipc_fallback",
        "requested_mode": "shm",
        "effective_mode": "zmq",
        "reason": reason,
        "mapping_name": SHM_MAPPING_NAME,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _log_startup("ipc", shm_timeout=True, fallback="zmq", reason=reason)
    logger.warning("IPC fallback activated: %s", json.dumps(fallback_event))
    consumer = ZmqConsumer(
        ZMQ_ADDRESS,
        queue,
        dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    )
    return consumer, "zmq", fallback_event


def _update_readiness_from_metrics(runtime: DistributorRuntime) -> None:
    if runtime.consumer is None or runtime.consumer_sync is None:
        startup_state.set_ready(False)
        startup_state.set_status("initializing")
        return

    if not runtime.consumer.is_alive() or not runtime.consumer_sync.is_alive():
        startup_state.set_ready(False)
        startup_state.set_status("consumer_error")
        startup_state.set_error("ipc_consumer_not_alive")
        return

    if not startup_state.snapshot().get("ready"):
        logger.info("[distributor.ready] true")
    startup_state.set_ready(True)
    startup_state.set_status("ready")
    startup_state.clear_error()


async def pipeline_health_loop(runtime: DistributorRuntime) -> None:
    """Unified distributor health snapshot for faster diagnosis."""
    while True:
        await asyncio.sleep(5)
        if runtime.consumer is None or runtime.consumer_sync is None:
            _update_readiness_from_metrics(runtime)
            continue

        backlog = runtime.queue.qsize()
        r = runtime.router.metrics()
        m = runtime.manager.metrics()
        c_main = runtime.consumer.metrics()
        c_sync = runtime.consumer_sync.metrics()
        c_aux = (
            runtime.consumer_zmq_market_aux.metrics()
            if runtime.consumer_zmq_market_aux is not None
            else None
        )
        dropped_dom = int(c_main["dropped_dom"] + c_sync["dropped_dom"])
        rescued = int(c_main["rescued_trade_like"] + c_sync["rescued_trade_like"])
        gap_c = int(c_main.get("gap_count", 0) + c_sync.get("gap_count", 0))
        gap_m = int(c_main.get("gap_messages", 0) + c_sync.get("gap_messages", 0))
        ring_d = int(c_main.get("ring_dropped", 0) + c_sync.get("ring_dropped", 0))
        integ = int(c_main.get("integrity_failures", 0) + c_sync.get("integrity_failures", 0))
        crc_m = int(c_main.get("crc_mismatch", 0) + c_sync.get("crc_mismatch", 0))
        pay_m = int(c_main.get("payload_mismatch", 0) + c_sync.get("payload_mismatch", 0))
        com_m = int(c_main.get("committed_mismatch", 0) + c_sync.get("committed_mismatch", 0))
        if c_aux is not None:
            dropped_dom += int(c_aux["dropped_dom"])
            rescued += int(c_aux["rescued_trade_like"])

        logger.info(
            "Pipeline health: mode=%s backlog=%s route_avg_ms=%.3f route_total=%s invalid_json=%s throttled_dom=%s dropped_dom=%s rescued_trade_like=%s gap_count=%s gap_messages=%s ring_dropped=%s integrity_failures=%s crc_mismatch=%s payload_mismatch=%s committed_mismatch=%s ws_clients=%s ws_queue_dropped=%s",
            runtime.effective_ipc_mode,
            backlog,
            float(r["route_avg_ms"]),
            int(r["route_count_total"]),
            int(r["invalid_json_count"]),
            int(r["throttled_dom_count"]),
            dropped_dom,
            rescued,
            gap_c,
            gap_m,
            ring_d,
            integ,
            crc_m,
            pay_m,
            com_m,
            int(m["connected_ws_clients"]),
            int(m["ui_client_queue_dropped"]),
        )

        if runtime.rag_engine is not None:
            rm = runtime.rag_engine.metrics()
            logger.info(
                "RAG health: events=%s windows=%s vectors=%s misses=%s query_ms=%.3f stream_ok=%s stream_fail=%s",
                int(rm.get("events_ingested_total", 0)),
                int(rm.get("windows_finalized_total", 0)),
                int(rm.get("vector_store_size", 0)),
                int(rm.get("vector_query_miss_total", 0)),
                float(rm.get("last_query_ms", 0.0)),
                int(rm.get("stream_published_total", 0)),
                int(rm.get("stream_publish_failures_total", 0)),
            )

        _update_readiness_from_metrics(runtime)


async def bootstrap_runtime(
    runtime: DistributorRuntime,
    *,
    app: Any | None = None,
) -> None:
    startup_state.set_ready(False)
    startup_state.set_status("initializing")
    startup_state.clear_error()

    loop = asyncio.get_running_loop()
    consumer, effective_ipc_mode, fallback_event = await asyncio.to_thread(
        resolve_market_consumer,
        runtime.queue,
    )
    consumer_zmq_market_aux: Optional[ZmqConsumer] = None
    if effective_ipc_mode == "shm":
        consumer_zmq_market_aux = ZmqConsumer(
            ZMQ_ADDRESS,
            runtime.queue,
            dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
            market_type_allowlist=frozenset(("volume_profile", "tape_intelligence", "daily")),
        )

    consumer_sync = ZmqConsumer(
        ZMQ_SYNC_ADDRESS,
        runtime.queue,
        dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    )

    init_app(
        runtime.manager,
        consumer,
        runtime.agent007_engine,
        runtime.router,
        volume_profile_connection_manager=runtime.vp_tape_manager,
        vp_overlay_connection_manager=runtime.vp_overlay_manager,
        rag_pipeline=runtime.rag_engine,
        sync_consumer=consumer_sync,
        zmq_market_aux=consumer_zmq_market_aux,
        market_queue_ref=runtime.queue,
        market_ipc_mode=effective_ipc_mode,
        fallback_event=fallback_event,
    )

    runtime.consumer = consumer
    runtime.consumer_sync = consumer_sync
    runtime.consumer_zmq_market_aux = consumer_zmq_market_aux
    runtime.effective_ipc_mode = effective_ipc_mode
    runtime.fallback_event = fallback_event

    startup_state.set_ipc_mode(effective_ipc_mode)
    startup_state.set_status("waiting_for_engine")
    logger.info(
        "Distributor IPC effective mode=%s (requested=%s) SHM_FALLBACK_PROBE_TIMEOUT_MS=%s",
        effective_ipc_mode,
        _ipc_mode_requested(),
        _ipc_probe_timeout_ms(),
    )

    consumer.start(loop=loop)
    consumer_sync.start(loop=loop)
    if consumer_zmq_market_aux is not None:
        consumer_zmq_market_aux.start(loop=loop)

    consume_task = _attach_task_guard(
        asyncio.create_task(consume_loop(runtime.queue, runtime.router)),
        name="consume_loop",
    )
    runtime.tasks.append(consume_task)
    runtime.tasks.append(
        _attach_task_guard(
            asyncio.create_task(runtime.router.ui_flush_loop()),
            name="ui_flush_loop",
        )
    )
    runtime.tasks.append(
        _attach_task_guard(
            asyncio.create_task(pipeline_health_loop(runtime)),
            name="pipeline_health_loop",
        )
    )
    startup_state.set_ready(True)
    startup_state.set_status("ready")
    startup_state.clear_error()
    if app is not None:
        app.state.market_consumer_task = consume_task
        app.state.runtime_tasks = runtime.tasks

    _log_startup("ipc", ready=True, mode=effective_ipc_mode)

    if runtime.rag_engine is None:
        logger.info("RAG mode disabled (set RAG_ENABLED=1 to enable M9 pipeline)")
    else:
        logger.info(
            "RAG mode enabled (window=%ss top_k=%s)",
            runtime.rag_engine.metrics().get("window_seconds"),
            runtime.rag_engine.metrics().get("top_k"),
        )


async def shutdown_runtime(runtime: DistributorRuntime) -> None:
    for task in runtime.tasks:
        task.cancel()
    if runtime.tasks:
        with suppress(Exception):
            await asyncio.gather(*runtime.tasks, return_exceptions=True)
    runtime.tasks.clear()

    if runtime.consumer is not None:
        runtime.consumer.stop()
    if runtime.consumer_sync is not None:
        runtime.consumer_sync.stop()
    if runtime.consumer_zmq_market_aux is not None:
        runtime.consumer_zmq_market_aux.stop()


if __name__ == "__main__":
    requested_mode = _ipc_mode_requested()
    startup_state.reset(ipc_mode=requested_mode)
    startup_state.set_status("starting")
    startup_state.set_ready(False)

    _log_startup(
        "startup",
        process_start=True,
        pid=os.getpid(),
        requested_ipc_mode=requested_mode,
        shm_timeout_ms=_ipc_probe_timeout_ms(),
    )

    runtime = build_runtime()

    @asynccontextmanager
    async def lifespan(app):  # noqa: ARG001
        startup_state.set_status("starting")
        logger.info("[distributor.startup] http_ready port=%s", WS_PORT)

        async def _run_bootstrap() -> None:
            await bootstrap_runtime(runtime, app=app)

        task = asyncio.create_task(_run_bootstrap())
        app.state.bootstrap_task = task

        def _on_bootstrap_done(done_task: asyncio.Task[Any]) -> None:
            if done_task.cancelled():
                return
            exc = done_task.exception()
            if exc is None:
                return
            startup_state.set_ready(False)
            startup_state.set_status("error")
            startup_state.set_error(f"bootstrap_failed: {exc}")
            logger.error(
                "Distributor bootstrap failed: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

        task.add_done_callback(_on_bootstrap_done)
        yield

        task = getattr(app.state, "bootstrap_task", None)
        if task is not None:
            task.cancel()
            with suppress(Exception):
                await task

        await shutdown_runtime(runtime)

    app = create_app(lifespan)

    try:
        uvicorn.run(app, host=WS_HOST, port=WS_PORT)
    except OSError as e:
        in_use = getattr(e, "winerror", None) == 10048 or getattr(e, "errno", None) == 98
        if in_use:
            logger.error(
                "Porta %s em uso. Feche o processo que a usa ou defina WS_PORT (ex: set WS_PORT=8001).",
                WS_PORT,
            )
        raise
