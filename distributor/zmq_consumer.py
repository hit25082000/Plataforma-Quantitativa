"""ZMQ SUB consumer running in a dedicated thread."""

import asyncio
import logging
import threading
from typing import Optional

import zmq

logger = logging.getLogger(__name__)

RCVTIMEO_MS = 100  # evita bloquear shutdown


class ZmqConsumer:
    """Consumes messages from ZMQ PUB socket and pushes to asyncio.Queue."""

    def __init__(self, address: str, queue: asyncio.Queue[str]) -> None:
        self._address = address
        self._queue = queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start the consumer thread (daemon). Pass the main thread's event loop so call_soon_threadsafe works."""
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("ZMQ consumer started, connecting to %s", self._address)

    def stop(self) -> None:
        """Signal the consumer to stop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def is_alive(self) -> bool:
        """Return True if the consumer thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def _put_msg(self, raw: str) -> None:
        """Put message in queue, discard with warning if full."""
        try:
            self._queue.put_nowait(raw)
        except asyncio.QueueFull:
            logger.warning("Market queue full, discarding message")

    def _run(self) -> None:
        """Loop in dedicated thread: receive from ZMQ, push to queue."""
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.RCVTIMEO, RCVTIMEO_MS)
        try:
            sock.connect(self._address)
            sock.setsockopt_string(zmq.SUBSCRIBE, "")  # subscribe to all
        except zmq.ZMQError as e:
            logger.error("ZMQ connect failed: %s", e)
            sock.close()
            ctx.term()
            return

        try:
            loop = self._loop
            while not self._stop_event.is_set():
                try:
                    raw = sock.recv_string()
                    if loop is not None:
                        loop.call_soon_threadsafe(self._put_msg, raw)
                    else:
                        self._put_msg(raw)
                except zmq.Again:
                    continue
                except zmq.ZMQError as e:
                    logger.warning("ZMQ recv error: %s", e)
                    break
        finally:
            sock.close()
            ctx.term()
            logger.info("ZMQ consumer stopped")
