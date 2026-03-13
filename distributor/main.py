"""Entry point for M3 Distribution Layer."""

import asyncio
import logging
import sys

import uvicorn

from config import (
    DOM_THROTTLE_MS,
    MARKET_QUEUE_MAXSIZE,
    WS_HOST,
    WS_PORT,
    ZMQ_ADDRESS,
)
from connection_manager import ConnectionManager
from message_router import MessageRouter
from websocket_server import app, init_app
from zmq_consumer import ZmqConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


async def consume_loop(queue: asyncio.Queue[str], router: MessageRouter) -> None:
    """Consume messages from queue and route to WebSocket clients."""
    while True:
        msg = await queue.get()
        await router.route(msg)


if __name__ == "__main__":
    queue = asyncio.Queue(maxsize=MARKET_QUEUE_MAXSIZE)
    manager = ConnectionManager()
    router = MessageRouter(manager, DOM_THROTTLE_MS)
    consumer = ZmqConsumer(ZMQ_ADDRESS, queue)

    init_app(manager, consumer)

    @app.on_event("startup")
    async def startup() -> None:
        consumer.start(loop=asyncio.get_running_loop())
        asyncio.create_task(consume_loop(queue, router))

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
