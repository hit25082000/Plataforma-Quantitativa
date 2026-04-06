"""Entry point for M3 Distribution Layer."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn

from agent_007 import Agent007Engine
from config import (
    DOM_THROTTLE_MS,
    MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    MARKET_QUEUE_MAXSIZE,
    WS_HOST,
    WS_PORT,
    ZMQ_ADDRESS,
    ZMQ_SYNC_ADDRESS,
)
from connection_manager import ConnectionManager
from message_router import MessageRouter
from websocket_server import create_app, init_app
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


if __name__ == "__main__":
    queue = asyncio.Queue(maxsize=MARKET_QUEUE_MAXSIZE)
    manager = ConnectionManager()
    agent007_engine = Agent007Engine()
    router = MessageRouter(manager, DOM_THROTTLE_MS, agent007_engine)
    consumer = ZmqConsumer(
        ZMQ_ADDRESS,
        queue,
        dom_soft_limit_pct=MARKET_QUEUE_DOM_SOFT_LIMIT_PCT,
    )
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
        sync_consumer=consumer_sync,
        market_queue_ref=queue,
    )

    async def pipeline_health_loop() -> None:
        """Unified distributor health snapshot for faster diagnosis."""
        while True:
            await asyncio.sleep(5)
            backlog = queue.qsize()
            r = router.metrics()
            c_main = consumer.metrics()
            c_sync = consumer_sync.metrics()
            logging.info(
                "Pipeline health: backlog=%s route_avg_ms=%.3f route_total=%s invalid_json=%s throttled_dom=%s dropped_dom=%s rescued_trade_like=%s",
                backlog,
                float(r["route_avg_ms"]),
                int(r["route_count_total"]),
                int(r["invalid_json_count"]),
                int(r["throttled_dom_count"]),
                int(c_main["dropped_dom"] + c_sync["dropped_dom"]),
                int(c_main["rescued_trade_like"] + c_sync["rescued_trade_like"]),
            )

    @asynccontextmanager
    async def lifespan(app):  # noqa: ARG001
        loop = asyncio.get_running_loop()
        consumer.start(loop=loop)
        consumer_sync.start(loop=loop)
        asyncio.create_task(consume_loop(queue, router))
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
