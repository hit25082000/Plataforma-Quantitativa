from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

import message_router


class _FakeConnectionManager:
    def __init__(self) -> None:
        self.frames: list[str] = []
        self.active: set[object] = {object()}

    async def broadcast(self, raw: str) -> None:
        self.frames.append(raw)


class _FakeAgent007:
    def on_flow_inversion(self, msg: dict) -> None:  # pragma: no cover
        return

    def on_macd(self, msg: dict) -> None:  # pragma: no cover
        return

    def on_trade(self, msg: dict) -> None:  # pragma: no cover
        return None

    def should_broadcast(self, msg: dict) -> bool:  # pragma: no cover
        return False


class TestMessageRouterUiAggregator(unittest.TestCase):
    def test_dom_snapshot_latest_wins(self) -> None:
        async def run() -> None:
            manager = _FakeConnectionManager()
            router = message_router.MessageRouter(
                manager,
                throttle_ms=100,
                agent007=_FakeAgent007(),
                ui_snapshot_interval_ms=10,
                ui_trade_batch_max_items=200,
            )
            for i in range(100):
                raw = json.dumps(
                    {"topic": "market", "type": "dom_snapshot", "ticker": "WINFUT", "seq": i}
                )
                await router.route(raw)
            await router.flush_ui_once()
            self.assertGreaterEqual(len(manager.frames), 1)
            payload = json.loads(manager.frames[-1])
            self.assertEqual(payload.get("type"), "dom_snapshot")
            self.assertEqual(int(payload.get("seq", -1)), 99)

        asyncio.run(run())

    def test_alert_is_immediate(self) -> None:
        async def run() -> None:
            manager = _FakeConnectionManager()
            router = message_router.MessageRouter(
                manager,
                throttle_ms=100,
                agent007=_FakeAgent007(),
                ui_snapshot_interval_ms=10,
            )
            await router.route(json.dumps({"topic": "alert", "type": "test_alert", "msg": "x"}))
            self.assertEqual(len(manager.frames), 1)
            payload = json.loads(manager.frames[0])
            self.assertEqual(payload.get("topic"), "alert")

        asyncio.run(run())

    def test_trade_is_batched(self) -> None:
        async def run() -> None:
            manager = _FakeConnectionManager()
            router = message_router.MessageRouter(
                manager,
                throttle_ms=100,
                agent007=_FakeAgent007(),
                ui_snapshot_interval_ms=10,
                ui_trade_batch_max_items=20,
            )
            for i in range(35):
                await router.route(
                    json.dumps(
                        {
                            "topic": "market",
                            "type": "trade",
                            "ticker": "WINFUT",
                            "price": 100000 + (i % 3) * 5,
                            "qty": 1,
                            "side": "buy" if i % 2 == 0 else "sell",
                        }
                    )
                )
            await router.flush_ui_once()
            self.assertEqual(len(manager.frames), 1)
            payload = json.loads(manager.frames[0])
            self.assertEqual(payload.get("topic"), "market")
            self.assertEqual(payload.get("type"), "trade_batch")
            self.assertGreater(int(payload.get("batch_size", 0)), 0)
            self.assertIn("items", payload)

        asyncio.run(run())

    def test_trade_batch_respects_limit_and_aggregates_overflow(self) -> None:
        async def run() -> None:
            manager = _FakeConnectionManager()
            router = message_router.MessageRouter(
                manager,
                throttle_ms=100,
                agent007=_FakeAgent007(),
                ui_snapshot_interval_ms=10,
                ui_trade_batch_max_items=10,
            )
            for _ in range(25):
                await router.route(
                    json.dumps(
                        {
                            "topic": "market",
                            "type": "trade",
                            "ticker": "WINFUT",
                            "price": 100000,
                            "qty": 1,
                            "side": "buy",
                        }
                    )
                )
            await router.flush_ui_once()
            self.assertEqual(len(manager.frames), 1)
            payload = json.loads(manager.frames[0])
            self.assertEqual(payload.get("type"), "trade_batch")
            self.assertEqual(int(payload.get("overflow_aggregated", -1)), 1)
            self.assertEqual(int(payload.get("batch_size", -1)), 11)
            items = payload.get("items", [])
            self.assertEqual(len(items), 11)
            self.assertEqual(items[-1].get("type"), "trade_agg")
            self.assertEqual(int(items[-1].get("count", -1)), 15)
            self.assertEqual(int(items[-1].get("qty", -1)), 15)

        asyncio.run(run())

    def test_latest_visual_skips_publish_when_payload_unchanged(self) -> None:
        async def run() -> None:
            manager = _FakeConnectionManager()
            router = message_router.MessageRouter(
                manager,
                throttle_ms=100,
                agent007=_FakeAgent007(),
                ui_snapshot_interval_ms=10,
                ui_trade_batch_max_items=20,
            )
            payload = {
                "topic": "market",
                "type": "dom_snapshot",
                "ticker": "WINFUT",
                "seq": 7,
                "buy": [],
                "sell": [],
            }
            await router.route(json.dumps(payload))
            await router.flush_ui_once()
            self.assertEqual(len(manager.frames), 1)

            await router.route(json.dumps(payload))
            await router.flush_ui_once()
            self.assertEqual(len(manager.frames), 1)

            metrics = router.metrics()
            self.assertGreaterEqual(int(metrics.get("ui_skipped_same_payload", 0)), 1)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
