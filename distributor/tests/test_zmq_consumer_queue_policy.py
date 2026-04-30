"""Testes de política de fila (pressão) do ZmqConsumer."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from zmq_consumer import ZmqConsumer


def _raw(msg_type: str) -> str:
    return json.dumps({"topic": "market", "type": msg_type})


class TestZmqConsumerQueuePolicy(unittest.TestCase):
    def _make_consumer(self, maxsize: int = 10, soft_limit_pct: int = 70) -> tuple[ZmqConsumer, asyncio.Queue[str]]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        consumer = ZmqConsumer("tcp://127.0.0.1:5555", queue, dom_soft_limit_pct=soft_limit_pct)
        return consumer, queue

    def test_drops_wall_remove_preemptively_when_soft_limit_reached(self) -> None:
        consumer, queue = self._make_consumer(maxsize=10, soft_limit_pct=70)
        for _ in range(7):
            queue.put_nowait(_raw("trade"))

        consumer._put_msg(_raw("wall_remove"))

        self.assertEqual(queue.qsize(), 7)
        metrics = consumer.metrics()
        self.assertEqual(metrics["dropped_low_priority"], 1)
        self.assertEqual(metrics["dropped_dom"], 0)

    def test_keeps_wall_remove_when_queue_is_healthy(self) -> None:
        consumer, queue = self._make_consumer(maxsize=10, soft_limit_pct=70)

        consumer._put_msg(_raw("wall_remove"))

        self.assertEqual(queue.qsize(), 1)
        metrics = consumer.metrics()
        self.assertEqual(metrics["dropped_low_priority"], 0)

    def test_trade_still_rescues_by_evicting_dom_snapshot_when_queue_full(self) -> None:
        consumer, queue = self._make_consumer(maxsize=2, soft_limit_pct=99)
        queue.put_nowait(_raw("dom_snapshot"))
        queue.put_nowait(_raw("wall_remove"))

        consumer._put_msg(_raw("trade"))

        items = list(queue._queue)  # type: ignore[attr-defined]
        self.assertEqual(len(items), 2)
        msg_types = [json.loads(item)["type"] for item in items]
        self.assertIn("trade", msg_types)
        self.assertIn("wall_remove", msg_types)
        self.assertNotIn("dom_snapshot", msg_types)
        metrics = consumer.metrics()
        self.assertEqual(metrics["rescued_trade_like"], 1)
        self.assertEqual(metrics["evicted_dom"], 1)


if __name__ == "__main__":
    unittest.main()
