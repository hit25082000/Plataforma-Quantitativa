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


class TestMessageRouterVpTape(unittest.TestCase):
    def setUp(self) -> None:
        self._old_enrich = message_router.enrich_vp_ti_message

    def tearDown(self) -> None:
        message_router.enrich_vp_ti_message = self._old_enrich

    def test_volume_profile_is_enriched_and_sent_to_both_channels(self) -> None:
        def _enrich(msg: dict) -> dict:
            out = dict(msg)
            out["poc_y"] = 123
            return out

        message_router.enrich_vp_ti_message = _enrich
        main_manager = _FakeConnectionManager()
        vp_manager = _FakeConnectionManager()
        router = message_router.MessageRouter(
            main_manager,
            throttle_ms=100,
            agent007=_FakeAgent007(),
            vp_tape_manager=vp_manager,
        )
        raw = json.dumps({"topic": "market", "type": "volume_profile", "poc": 100})

        asyncio.run(router.route(raw))

        self.assertEqual(len(main_manager.frames), 1)
        self.assertEqual(len(vp_manager.frames), 1)
        self.assertEqual(main_manager.frames[0], vp_manager.frames[0])
        enriched = json.loads(main_manager.frames[0])
        self.assertEqual(enriched["poc_y"], 123)

    def test_non_vp_tape_message_does_not_use_dedicated_channel(self) -> None:
        main_manager = _FakeConnectionManager()
        vp_manager = _FakeConnectionManager()
        router = message_router.MessageRouter(
            main_manager,
            throttle_ms=100,
            agent007=_FakeAgent007(),
            vp_tape_manager=vp_manager,
        )
        raw = json.dumps({"topic": "market", "type": "daily", "trade_date": "2026-04-26"})

        asyncio.run(router.route(raw))
        asyncio.run(router.flush_ui_once())

        self.assertEqual(len(main_manager.frames), 1)
        self.assertEqual(len(vp_manager.frames), 0)

    def test_tape_intelligence_joins_with_last_volume_profile(self) -> None:
        def _enrich(msg: dict) -> dict:
            out = dict(msg)
            if out.get("type") == "volume_profile":
                out["poc_y"] = 111
                out["vah_y"] = 101
                out["val_y"] = 121
            return out

        message_router.enrich_vp_ti_message = _enrich
        main_manager = _FakeConnectionManager()
        vp_manager = _FakeConnectionManager()
        router = message_router.MessageRouter(
            main_manager,
            throttle_ms=100,
            agent007=_FakeAgent007(),
            vp_tape_manager=vp_manager,
        )
        vp_raw = json.dumps(
            {
                "topic": "market",
                "type": "volume_profile",
                "ticker": "WINFUT",
                "period": "day",
                "price_step": 5,
                "total_vol": 1000,
                "poc": 100,
                "vah": 110,
                "val": 90,
                "levels": [{"price": 100, "total_vol": 500}],
            }
        )
        ti_raw = json.dumps(
            {
                "topic": "market",
                "type": "tape_intelligence",
                "ticker": "WINFUT",
                "poc_price": 100,
                "vah_price": 110,
                "val_price": 90,
                "poc_player": 1,
                "val_buyer": 2,
                "vah_seller": 3,
                "poc_top3": [],
                "vah_top3": [],
                "val_top3": [],
            }
        )

        asyncio.run(router.route(vp_raw))
        asyncio.run(router.route(ti_raw))

        self.assertEqual(len(main_manager.frames), 2)
        ti_out = json.loads(main_manager.frames[1])
        self.assertEqual(ti_out["period"], "day")
        self.assertEqual(ti_out["price_step"], 5)
        self.assertEqual(ti_out["total_vol"], 1000)
        self.assertEqual(ti_out["poc"], 100)
        self.assertEqual(ti_out["vah"], 110)
        self.assertEqual(ti_out["val"], 90)
        self.assertEqual(ti_out["levels"], [{"price": 100, "total_vol": 500}])
        self.assertEqual(ti_out["poc_y"], 111)
        self.assertEqual(ti_out["vah_y"], 101)
        self.assertEqual(ti_out["val_y"], 121)


if __name__ == "__main__":
    unittest.main()
