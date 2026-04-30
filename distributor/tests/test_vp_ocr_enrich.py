from __future__ import annotations

import os
import sys
import time
import unittest
import urllib.error
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

import vp_ocr_enrich


class TestVpOcrEnrich(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = os.environ.get("VP_ENRICH_OCR")
        self._old_get_axis_pack = vp_ocr_enrich._get_axis_pack
        vp_ocr_enrich._CACHE_PACK = None
        vp_ocr_enrich._CACHE_TS_MS = 0.0
        vp_ocr_enrich._STATUS_BODY = None
        vp_ocr_enrich._STATUS_BODY_MS = 0.0
        vp_ocr_enrich._STATUS_FAIL_MS = 0.0
        vp_ocr_enrich._STATUS_FAIL_LOG_MS = 0.0

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("VP_ENRICH_OCR", None)
        else:
            os.environ["VP_ENRICH_OCR"] = self._old_env
        vp_ocr_enrich._get_axis_pack = self._old_get_axis_pack

    def test_enriches_volume_profile_and_levels(self) -> None:
        os.environ["VP_ENRICH_OCR"] = "1"
        vp_ocr_enrich._get_axis_pack = lambda: (
            [
                {"value": 100.0, "y_screen": 200.0},
                {"value": 110.0, "y_screen": 100.0},
            ],
            {"slope": -0.1, "intercept": 120.0, "value_per_px": 0.1},
            {"top": 0, "bottom": 300},
        )
        msg = {
            "topic": "market",
            "type": "volume_profile",
            "poc": 105,
            "vah": 110,
            "val": 100,
            "levels": [{"price": 100}, {"price": 105}, {"price": 110}],
        }

        out = vp_ocr_enrich.enrich_vp_ti_message(msg)

        self.assertEqual(out["poc_y"], 150)
        self.assertEqual(out["vah_y"], 100)
        self.assertEqual(out["val_y"], 200)
        self.assertEqual(out["levels"][0]["y"], 200)
        self.assertEqual(out["levels"][1]["y"], 150)
        self.assertEqual(out["levels"][2]["y"], 100)

    def test_enriches_tape_intelligence_prices(self) -> None:
        os.environ["VP_ENRICH_OCR"] = "1"
        vp_ocr_enrich._get_axis_pack = lambda: (
            [
                {"value": 100.0, "y_screen": 220.0},
                {"value": 120.0, "y_screen": 120.0},
            ],
            {"slope": -0.2, "intercept": 144.0, "value_per_px": 0.2},
            None,
        )
        msg = {
            "topic": "market",
            "type": "tape_intelligence",
            "poc_price": 110.0,
            "vah_price": 120.0,
            "val_price": 100.0,
        }

        out = vp_ocr_enrich.enrich_vp_ti_message(msg)

        self.assertEqual(out["poc_y"], 170)
        self.assertEqual(out["vah_y"], 120)
        self.assertEqual(out["val_y"], 220)

    def test_skips_when_disabled(self) -> None:
        os.environ["VP_ENRICH_OCR"] = "0"
        msg = {"topic": "market", "type": "volume_profile", "poc": 105}

        out = vp_ocr_enrich.enrich_vp_ti_message(msg)

        self.assertIs(out, msg)
        self.assertNotIn("poc_y", out)

    def test_enrich_vp_overlay_health_and_axis(self) -> None:
        os.environ["VP_ENRICH_OCR"] = "1"
        old_fetch = vp_ocr_enrich._fetch_ocr_status_body

        def fake_fetch() -> dict:
            ts = time.time()
            return {
                "status": "ok",
                "last_update": ts - 0.45,
                "y_min": 100.0,
                "y_max": 120.0,
                "chart_rect": {"left": 10, "top": 20, "width": 800, "height": 400},
                "axis_labels": [
                    {"value": 100.0, "y_screen": 250.0},
                    {"value": 120.0, "y_screen": 50.0},
                ],
                "axis": {"slope": -0.1, "intercept": 125.0},
                "axis_diagnostics": {"raw_labels": 8, "kept_labels": 6, "rejected": 2},
            }

        vp_ocr_enrich._fetch_ocr_status_body = fake_fetch  # type: ignore[method-assign]
        try:
            payload = {
                "topic": "market",
                "type": "vp_overlay",
                "version": 1,
                "symbol": "WINFUT",
                "scope": "session",
                "sequence": 1,
                "updated_at": time.time(),
                "poc": {"price": 110.0, "player_id": 1, "label": "POC"},
                "val": {"price": 100.0, "player_id": 2, "label": "VAL"},
                "vah": {"price": 120.0, "player_id": 3, "label": "VAH"},
                "levels": [{"price": 110.0, "total_vol": 1, "bid_vol": 0, "ask_vol": 0, "pct_of_max": 1.0}],
                "top_player_avg_lines": [],
                "display": {
                    "overlay_enabled": True,
                    "poc_visible": True,
                    "val_vah_visible": True,
                    "labels_visible": True,
                    "histogram_visible": True,
                    "top_avg_visible": True,
                    "stretch_lines": False,
                    "max_avg_lines": 6,
                    "max_histogram_width_px": 220,
                    "max_visible_histogram_levels": 400,
                },
                "health": {"data_status": "ok", "axis_stale_ms": 0, "last_trade_age_ms": 0, "ocr_confidence": 0.0},
            }
            out = vp_ocr_enrich.enrich_vp_overlay_payload(payload)
            self.assertGreaterEqual(out["health"]["axis_stale_ms"], 300)
            self.assertLess(out["health"]["axis_stale_ms"], 1200)
            self.assertGreater(out["health"]["ocr_confidence"], 0.4)
            self.assertIn("axis", out)
            self.assertEqual(out["axis"]["status"], "ok")
            self.assertAlmostEqual(out["axis"]["slope"], -0.1)
            self.assertEqual(out["axis"]["chart_bounds"]["right"], 810.0)
            self.assertEqual(out["poc"]["y"], 150)
            self.assertEqual(out["val"]["y"], 250)
            self.assertEqual(out["vah"]["y"], 50)
            self.assertEqual(out["levels"][0]["y"], 150)
        finally:
            vp_ocr_enrich._fetch_ocr_status_body = old_fetch  # type: ignore[method-assign]

    def test_ocr_status_failure_is_negatively_cached(self) -> None:
        old_urlopen = vp_ocr_enrich.urllib.request.urlopen
        calls = 0

        def fake_urlopen(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise urllib.error.URLError("offline")

        vp_ocr_enrich.urllib.request.urlopen = fake_urlopen  # type: ignore[method-assign]
        try:
            self.assertIsNone(vp_ocr_enrich._fetch_ocr_status_body())
            self.assertIsNone(vp_ocr_enrich._fetch_ocr_status_body())
            self.assertEqual(calls, 1)
        finally:
            vp_ocr_enrich.urllib.request.urlopen = old_urlopen  # type: ignore[method-assign]


if __name__ == "__main__":
    unittest.main()
