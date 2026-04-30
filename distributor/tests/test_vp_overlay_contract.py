from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


CONTRACT_PATH = _ROOT / "docs" / "contracts" / "vp-overlay-v1.json"
FIXTURE_PATH = _ROOT / "docs" / "contracts" / "fixtures" / "vp-overlay-demo.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise AssertionError(f"{path} did not contain a JSON object")
    return data


def _assert_anchor(testcase: unittest.TestCase, anchor: Any) -> None:
    testcase.assertIsInstance(anchor, dict)
    testcase.assertIn("price", anchor)
    testcase.assertIn("player_id", anchor)
    testcase.assertIn("label", anchor)
    testcase.assertIsInstance(anchor["price"], (int, float))
    testcase.assertIsInstance(anchor["player_id"], int)
    testcase.assertIsInstance(anchor["label"], str)


def _assert_holder(testcase: unittest.TestCase, holder: Any) -> None:
    testcase.assertIsInstance(holder, dict)
    testcase.assertIn("method", holder)
    testcase.assertIn("state", holder)
    testcase.assertIn(holder["method"], {
        "total_volume",
        "passive_buy_absorption",
        "passive_sell_absorption",
        "unconfirmed",
    })
    testcase.assertIn(holder["state"], {"ok", "low_confidence", "unconfirmed"})
    if "contracts" in holder:
        testcase.assertIsInstance(holder["contracts"], int)
        testcase.assertGreaterEqual(holder["contracts"], 0)
    if "participation_pct" in holder:
        testcase.assertIsInstance(holder["participation_pct"], (int, float))
        testcase.assertGreaterEqual(holder["participation_pct"], 0)
        testcase.assertLessEqual(holder["participation_pct"], 100)


class TestVpOverlayContract(unittest.TestCase):
    def test_fixture_matches_expected_contract_shape(self) -> None:
        schema = _load_json(CONTRACT_PATH)
        fixture = _load_json(FIXTURE_PATH)

        self.assertEqual(schema["title"], "vp_overlay")
        self.assertEqual(schema["properties"]["type"]["const"], "vp_overlay")
        self.assertEqual(schema["properties"]["version"]["const"], 1)

        required = set(schema["required"])
        self.assertTrue(required.issubset(fixture.keys()))
        self.assertEqual(fixture["type"], "vp_overlay")
        self.assertEqual(fixture["version"], 1)
        self.assertEqual(fixture["topic"], "market")
        self.assertEqual(fixture["symbol"], "WINFUT")
        self.assertEqual(fixture["raw_ticker"], "WINFUT · BMF")
        self.assertIn(fixture["scope"], {"session", "day", "week", "manual"})

        _assert_anchor(self, fixture["poc"])
        _assert_anchor(self, fixture["val"])
        _assert_anchor(self, fixture["vah"])
        _assert_holder(self, fixture["poc"]["holder"])
        _assert_holder(self, fixture["val"]["holder"])
        _assert_holder(self, fixture["vah"]["holder"])

        self.assertIsInstance(fixture["levels"], list)
        self.assertGreaterEqual(len(fixture["levels"]), 1)
        for row in fixture["levels"]:
            self.assertIsInstance(row, dict)
            self.assertIsInstance(row["price"], (int, float))
            self.assertIsInstance(row["total_vol"], int)
            self.assertGreaterEqual(row["total_vol"], 0)
            self.assertIn("pct_of_max", row)

        self.assertIsInstance(fixture["top_player_avg_lines"], list)
        self.assertGreaterEqual(len(fixture["top_player_avg_lines"]), 1)
        for row in fixture["top_player_avg_lines"]:
            self.assertIsInstance(row, dict)
            self.assertIsInstance(row["player_id"], int)
            self.assertIn(row["mode"], {"total", "buy", "sell", "net"})
            self.assertIsInstance(row["avg_price"], (int, float))
            self.assertIsInstance(row["label"], str)

        display = fixture["display"]
        self.assertIsInstance(display, dict)
        self.assertTrue(display["overlay_enabled"])
        self.assertTrue(display["poc_visible"])
        self.assertTrue(display["val_vah_visible"])
        self.assertTrue(display["labels_visible"])
        self.assertTrue(display["histogram_visible"])
        self.assertTrue(display["top_avg_visible"])

        health = fixture["health"]
        self.assertIsInstance(health, dict)
        self.assertEqual(health["data_status"], "ok")
        self.assertIsInstance(health["ocr_confidence"], (int, float))
        self.assertGreaterEqual(health["ocr_confidence"], 0)
        self.assertLessEqual(health["ocr_confidence"], 1)
        self.assertIn("last_overlay_publish_age_ms", health)
        self.assertIn("last_overlay_publish_age_sec", health)
        self.assertIn(health["overlay_age_state"], {"fresh", "stale", "missing"})

    def test_schema_freezes_expected_overlay_contract_fields(self) -> None:
        schema = _load_json(CONTRACT_PATH)
        props = schema["properties"]

        for field in ["topic", "type", "version", "symbol", "raw_ticker", "scope", "sequence", "updated_at", "poc", "val", "vah", "levels", "top_player_avg_lines", "display", "health"]:
            self.assertIn(field, props)

        self.assertIn("axis", props)
        self.assertIn("demo", props)
        self.assertIn("raw_ticker", props)

        holder_enum = schema["$defs"]["holder"]["properties"]["method"]["enum"]
        self.assertIn("passive_buy_absorption", holder_enum)
        self.assertIn("passive_sell_absorption", holder_enum)


if __name__ == "__main__":
    unittest.main()
