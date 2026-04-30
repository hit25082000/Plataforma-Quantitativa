"""Entry point for M3 Distribution Layer."""

import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn

from agent_007 import Agent007Engine
from config import (
    DOM_THROTTLE_MS,
    IPC_MODE,
    MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    MARKET_QUEUE_MAXSIZE,
    UI_CLIENT_QUEUE_MAXSIZE,
    SHM_FALLBACK_PROBE_INTERVAL_MS,
    SHM_FALLBACK_PROBE_TIMEOUT_MS,
    SHM_MAPPING_NAME,
    SHM_SIZE_MB,
    WS_HOST,
    WS_PORT,
    ZMQ_ADDRESS,
    ZMQ_SYNC_ADDRESS,
)
from connection_manager import ConnectionManager
from message_router import MessageRouter
from vp_overlay_consolidator import VpOverlayConsolidator
from websocket_server import create_app, init_app
from mmap_consumer import MmapConsumer
from realtime_rag import create_rag_engine_from_config
from zmq_consumer import ZmqConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


async def consume_loop(queue: asyncio.Queue[str], router: MessageRouter) -> None:
    """Consume messages from queue and route to WebSocket clients."""
    last_log_ms = 0.0
    while True:
        msg = await queue.get()
        await router.route(msg)
        now_ms = asyncio.get_running_loop().time() * 1000
        if now_ms - last_log_ms >= 5000:
            backlog = queue.qsize()
            if backlog > 0:
                logging.info("Consume loop backlog=%s messages", backlog)
            last_log_ms = now_ms


def resolve_market_consumer(queue: asyncio.Queue[str]) -> tuple[object, str, dict | None]:
    """Build market consumer with one-way startup fallback shm->zmq."""
    if IPC_MODE != "shm":
        consumer = ZmqConsumer(
            ZMQ_ADDRESS,
            queue,
            dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
        )
        return consumer, "zmq", None

    map_size_bytes = SHM_SIZE_MB * 1024 * 1024
    deadline = time.monotonic() + max(200, SHM_FALLBACK_PROBE_TIMEOUT_MS) / 1000.0
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
    logging.warning("IPC fallback activated: %s", json.dumps(fallback_event))
    consumer = ZmqConsumer(
        ZMQ_ADDRESS,
        queue,
        dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    )
    return consumer, "zmq", fallback_event


if __name__ == "__main__":
    queue = asyncio.Queue(maxsize=MARKET_QUEUE_MAXSIZE)
    manager = ConnectionManager(client_queue_maxsize=UI_CLIENT_QUEUE_MAXSIZE)
    vp_tape_manager = ConnectionManager(client_queue_maxsize=UI_CLIENT_QUEUE_MAXSIZE)
    vp_overlay_manager = ConnectionManager(
        client_queue_maxsize=1,
        dropped_metric_key="vp_overlay_client_queue_dropped",
    )
    vp_overlay_consolidator = VpOverlayConsolidator(publish_interval_ms=125)
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
    consumer, effective_ipc_mode, fallback_event = resolve_market_consumer(queue)
    consumer_zmq_market_aux: Optional[ZmqConsumer] = None
    if effective_ipc_mode == "shm":
        logging.info("Distributor IPC mode=shm mapping=%s size_mb=%s", SHM_MAPPING_NAME, SHM_SIZE_MB)
        consumer_zmq_market_aux = ZmqConsumer(
            ZMQ_ADDRESS,
            queue,
            dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
            market_type_allowlist=frozenset(
                ("volume_profile", "tape_intelligence", "daily")
            ),
        )
    else:
        logging.info("Distributor IPC mode=zmq address=%s", ZMQ_ADDRESS)
    consumer_sync = ZmqConsumer(
        ZMQ_SYNC_ADDRESS,
        queue,
        dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    )

    init_app(
        manager,
        consumer,
        agent007_engine,
        router,
        volume_profile_connection_manager=vp_tape_manager,
        vp_overlay_connection_manager=vp_overlay_manager,
        rag_pipeline=rag_engine,
        sync_consumer=consumer_sync,
        zmq_market_aux=consumer_zmq_market_aux,
        market_queue_ref=queue,
        market_ipc_mode=effective_ipc_mode,
        fallback_event=fallback_event,
    )
    if rag_engine is None:
        logging.info("RAG mode disabled (set RAG_ENABLED=1 to enable M9 pipeline)")
    else:
        logging.info("RAG mode enabled (window=%ss top_k=%s)", rag_engine.metrics().get("window_seconds"), rag_engine.metrics().get("top_k"))

    async def pipeline_health_loop() -> None:
        """Unified distributor health snapshot for faster diagnosis."""
        while True:
            await asyncio.sleep(5)
            backlog = queue.qsize()
            r = router.metrics()
            m = manager.metrics()
            c_main = consumer.metrics()
            c_sync = consumer_sync.metrics()
            c_aux = (
                consumer_zmq_market_aux.metrics()
                if consumer_zmq_market_aux is not None
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
            logging.info(
                "Pipeline health: mode=%s backlog=%s route_avg_ms=%.3f route_total=%s invalid_json=%s throttled_dom=%s dropped_dom=%s rescued_trade_like=%s gap_count=%s gap_messages=%s ring_dropped=%s integrity_failures=%s crc_mismatch=%s payload_mismatch=%s committed_mismatch=%s ws_clients=%s ws_queue_dropped=%s",
                effective_ipc_mode,
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
            if rag_engine is not None:
                rm = rag_engine.metrics()
                logging.info(
                    "RAG health: events=%s windows=%s vectors=%s misses=%s query_ms=%.3f stream_ok=%s stream_fail=%s",
                    int(rm.get("events_ingested_total", 0)),
                    int(rm.get("windows_finalized_total", 0)),
                    int(rm.get("vector_store_size", 0)),
                    int(rm.get("vector_query_miss_total", 0)),
                    float(rm.get("last_query_ms", 0.0)),
                    int(rm.get("stream_published_total", 0)),
                    int(rm.get("stream_publish_failures_total", 0)),
                )

    @asynccontextmanager
    async def lifespan(app):  # noqa: ARG001
        loop = asyncio.get_running_loop()
        consumer.start(loop=loop)
        consumer_sync.start(loop=loop)
        if consumer_zmq_market_aux is not None:
            consumer_zmq_market_aux.start(loop=loop)
        asyncio.create_task(consume_loop(queue, router))
        asyncio.create_task(router.ui_flush_loop())
        asyncio.create_task(pipeline_health_loop())
        yield

    app = create_app(lifespan)

    try:
        uvicorn.run(app, host=WS_HOST, port=WS_PORT)
    except OSError as e:
        in_use = getattr(e, "winerror", None) == 10048 or getattr(e, "errno", None) == 98
        if in_use:
            logging.error(
                "Porta %s em uso. Feche o processo que a usa ou defina WS_PORT (ex: set WS_PORT=8001).",
                WS_PORT,
            )
        raise
