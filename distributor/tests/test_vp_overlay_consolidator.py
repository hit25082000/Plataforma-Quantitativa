from __future__ import annotations

import sys
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from vp_overlay_consolidator import VpOverlayConsolidator, build_vp_overlay_payload


class TestVpOverlayConsolidator(unittest.TestCase):
    def test_build_payload_shape(self) -> None:
        vp = {
            "topic": "market",
            "type": "volume_profile",
            "ticker": "WINFUT",
            "period": "day",
            "poc": 100.0,
            "val": 99.0,
            "vah": 101.0,
            "levels": [
                {"price": 101.0, "total_vol": 8, "bid_vol": 4, "ask_vol": 4, "pct_of_max": 0.8},
                {"price": 100.0, "total_vol": 10, "bid_vol": 5, "ask_vol": 5, "pct_of_max": 1.0},
                {"price": 99.0, "total_vol": 6, "bid_vol": 3, "ask_vol": 3, "pct_of_max": 0.6},
            ],
        }
        tape = {
            "topic": "market",
            "type": "tape_intelligence",
            "ticker": "WINFUT",
            "timestamp": 1,
            "poc_price": 100,
            "val_price": 99,
            "vah_price": 101,
            "poc_player": 11,
            "val_buyer": 22,
            "vah_seller": 33,
            "poc_top3": [{"player": 11, "price": 100, "total_vol": 50, "bid_vol": 25, "ask_vol": 25}],
            "val_top3": [
                {"player": 22, "price": 99, "total_vol": 40, "bid_vol": 10, "ask_vol": 5, "buy_absorption": 30}
            ],
            "vah_top3": [
                {"player": 33, "price": 101, "total_vol": 35, "bid_vol": 5, "ask_vol": 10, "sell_absorption": 28}
            ],
            "val_holder_state": "ok",
            "vah_holder_state": "ok",
        }
        out = build_vp_overlay_payload(vp=vp, tape=tape, sequence=3, demo=True)
        self.assertEqual(out["type"], "vp_overlay")
        self.assertEqual(out["version"], 1)
        self.assertEqual(out["symbol"], "WINFUT")
        self.assertEqual(out["sequence"], 3)
        self.assertTrue(out["demo"])
        self.assertEqual(out["poc"]["holder"]["method"], "total_volume")
        self.assertEqual(out["val"]["holder"]["method"], "passive_buy_absorption")
        self.assertEqual(out["vah"]["holder"]["method"], "passive_sell_absorption")
        self.assertEqual(len(out["levels"]), 3)
        self.assertIn("last_overlay_publish_age_ms", out["health"])
        self.assertIn("last_overlay_publish_age_sec", out["health"])

    def test_feed_vp_then_tape(self) -> None:
        c = VpOverlayConsolidator(publish_interval_ms=0)
        vp = {
            "topic": "market",
            "type": "volume_profile",
            "ticker": "WINFUT",
            "period": "manual",
            "poc": 1.0,
            "val": 0.0,
            "vah": 2.0,
            "levels": [
                {"price": 2.0, "total_vol": 2, "bid_vol": 1, "ask_vol": 1, "pct_of_max": 1.0},
                {"price": 1.0, "total_vol": 1, "bid_vol": 1, "ask_vol": 0, "pct_of_max": 0.5},
                {"price": 0.0, "total_vol": 1, "bid_vol": 0, "ask_vol": 1, "pct_of_max": 0.5},
            ],
        }
        tape = {
            "topic": "market",
            "type": "tape_intelligence",
            "ticker": "WINFUT",
            "timestamp": 1,
            "poc_price": 1,
            "val_price": 0,
            "vah_price": 2,
            "poc_player": 1,
            "val_buyer": 2,
            "vah_seller": 3,
            "poc_top3": [],
            "val_top3": [],
            "vah_top3": [],
        }
        self.assertIsNone(c.feed_market_message(vp))
        first = c.feed_market_message(tape)
        self.assertIsNotNone(first)
        self.assertEqual(first["type"], "vp_overlay")
        second = c.feed_market_message(dict(tape))
        self.assertIsNone(second)

    def test_same_hash_skipped(self) -> None:
        c = VpOverlayConsolidator(publish_interval_ms=0)
        vp = {
            "topic": "market",
            "type": "volume_profile",
            "ticker": "X",
            "period": "manual",
            "poc": 1.0,
            "val": 0.0,
            "vah": 2.0,
            "levels": [
                {"price": 2.0, "total_vol": 2, "bid_vol": 1, "ask_vol": 1, "pct_of_max": 1.0},
                {"price": 1.0, "total_vol": 1, "bid_vol": 1, "ask_vol": 0, "pct_of_max": 0.5},
                {"price": 0.0, "total_vol": 1, "bid_vol": 0, "ask_vol": 1, "pct_of_max": 0.5},
            ],
        }
        tape = {
            "topic": "market",
            "type": "tape_intelligence",
            "ticker": "X",
            "timestamp": 1,
            "poc_price": 1,
            "val_price": 0,
            "vah_price": 2,
            "poc_player": 1,
            "val_buyer": 0,
            "vah_seller": 0,
            "poc_top3": [],
            "val_top3": [],
            "vah_top3": [],
        }
        c.feed_market_message(vp)
        c.feed_market_message(tape)
        self.assertGreaterEqual(c.metrics()["vp_overlay_emit_count"], 1)
        c.feed_market_message(dict(vp))
        c.feed_market_message(dict(tape))
        self.assertGreater(c.metrics()["vp_overlay_skipped_same_hash"], 0)

    def test_critical_change_bypasses_throttle(self) -> None:
        c = VpOverlayConsolidator(publish_interval_ms=60_000)
        vp = {
            "topic": "market",
            "type": "volume_profile",
            "ticker": "Z",
            "period": "manual",
            "poc": 1.0,
            "val": 0.0,
            "vah": 2.0,
            "levels": [
                {"price": 2.0, "total_vol": 2, "bid_vol": 1, "ask_vol": 1, "pct_of_max": 1.0},
                {"price": 1.0, "total_vol": 1, "bid_vol": 1, "ask_vol": 0, "pct_of_max": 0.5},
                {"price": 0.0, "total_vol": 1, "bid_vol": 0, "ask_vol": 1, "pct_of_max": 0.5},
            ],
        }
        tape = {
            "topic": "market",
            "type": "tape_intelligence",
            "ticker": "Z",
            "timestamp": 1,
            "poc_price": 1,
            "val_price": 0,
            "vah_price": 2,
            "poc_player": 1,
            "val_buyer": 2,
            "vah_seller": 3,
            "poc_top3": [],
            "val_top3": [],
            "vah_top3": [],
        }
        c.feed_market_message(vp)
        c.feed_market_message(tape)
        n0 = c.metrics()["vp_overlay_emit_count"]
        self.assertGreaterEqual(n0, 1)
        vp2 = dict(vp)
        vp2["poc"] = 9.0
        out = c.feed_market_message(vp2)
        self.assertIsNotNone(out)
        self.assertEqual(out["poc"]["price"], 9.0)
        self.assertGreater(c.metrics()["vp_overlay_emit_count"], n0)

    def test_debug_state_exposes_health_fields(self) -> None:
        c = VpOverlayConsolidator(publish_interval_ms=0)
        payload = {
            "topic": "market",
            "type": "vp_overlay",
            "version": 1,
            "symbol": "WINFUT",
            "scope": "day",
            "sequence": 7,
            "updated_at": 1.0,
            "poc": {"price": 100.0, "player_id": 1, "label": "POC"},
            "val": {"price": 99.0, "player_id": 2, "label": "VAL"},
            "vah": {"price": 101.0, "player_id": 3, "label": "VAH"},
            "levels": [],
            "top_player_avg_lines": [],
            "display": {},
            "health": {
                "data_status": "degraded",
                "axis_stale_ms": 321,
                "last_trade_age_ms": 654,
                "ocr_confidence": 0.72,
            },
        }

        c.inject_demo(payload)
        dbg = c.debug_state("WINFUT")

        self.assertEqual(dbg["data_status"], "degraded")
        self.assertEqual(dbg["last_trade_age_ms"], 654)
        self.assertEqual(dbg["ocr_confidence"], 0.72)
        self.assertIn("last_overlay_publish_age_ms", dbg)

    def test_same_hash_ignores_derived_overlay_fields(self) -> None:
        c = VpOverlayConsolidator(publish_interval_ms=0)
        vp = {
            "topic": "market",
            "type": "volume_profile",
            "ticker": "WINFUT",
            "period": "day",
            "poc": 100.0,
            "val": 99.0,
            "vah": 101.0,
            "levels": [
                {"price": 101.0, "total_vol": 8, "bid_vol": 4, "ask_vol": 4, "pct_of_max": 0.8},
                {"price": 100.0, "total_vol": 10, "bid_vol": 5, "ask_vol": 5, "pct_of_max": 1.0},
                {"price": 99.0, "total_vol": 6, "bid_vol": 3, "ask_vol": 3, "pct_of_max": 0.6},
            ],
        }
        tape = {
            "topic": "market",
            "type": "tape_intelligence",
            "ticker": "WINFUT",
            "timestamp": 1,
            "poc_price": 100,
            "val_price": 99,
            "vah_price": 101,
            "poc_player": 11,
            "val_buyer": 22,
            "vah_seller": 33,
            "poc_top3": [{"player": 11, "price": 100, "total_vol": 50, "bid_vol": 25, "ask_vol": 25}],
            "val_top3": [{"player": 22, "price": 99, "total_vol": 40, "bid_vol": 10, "ask_vol": 5, "buy_absorption": 30}],
            "vah_top3": [{"player": 33, "price": 101, "total_vol": 35, "bid_vol": 5, "ask_vol": 10, "sell_absorption": 28}],
            "val_holder_state": "ok",
            "vah_holder_state": "ok",
        }

        first = c.feed_market_message(vp)
        self.assertIsNone(first)
        first = c.feed_market_message(tape)
        self.assertIsNotNone(first)
        base_emits = c.metrics()["vp_overlay_emit_count"]

        derived = dict(first)
        derived["axis"] = {"status": "ok", "slope": -0.1, "intercept": 123.0}
        derived["demo"] = True
        c.inject_demo(derived)

        second = c.feed_market_message(dict(vp))
        self.assertIsNone(second)
        self.assertEqual(c.metrics()["vp_overlay_emit_count"], base_emits)


if __name__ == "__main__":
    unittest.main()
