from __future__ import annotations

import sys
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
import urllib.error

from fastapi.testclient import TestClient

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from connection_manager import ConnectionManager
from message_router import MessageRouter
from vp_overlay_consolidator import VpOverlayConsolidator
import websocket_server


class _FakeConsumer:
    def is_alive(self) -> bool:
        return True

    def metrics(self) -> dict[str, int]:
        return {
            "dropped_dom": 0,
            "rescued_trade_like": 0,
            "gap_count": 0,
            "gap_messages": 0,
            "ring_dropped": 0,
            "integrity_failures": 0,
            "crc_mismatch": 0,
            "payload_mismatch": 0,
            "committed_mismatch": 0,
        }


class TestVpOverlayEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.main_manager = ConnectionManager()
        self.vp_tape_manager = ConnectionManager()
        self.vp_overlay_manager = ConnectionManager()
        self.router = MessageRouter(
            self.main_manager,
            throttle_ms=0,
            vp_overlay_manager=self.vp_overlay_manager,
            vp_overlay_consolidator=VpOverlayConsolidator(publish_interval_ms=0),
        )
        websocket_server.init_app(
            self.main_manager,
            _FakeConsumer(),
            router=self.router,
            volume_profile_connection_manager=self.vp_tape_manager,
            vp_overlay_connection_manager=self.vp_overlay_manager,
        )
        self.client = TestClient(websocket_server.create_app())

    def _demo_payload(self) -> dict[str, object]:
        return {
            "topic": "market",
            "type": "vp_overlay",
            "version": 1,
            "symbol": "WINFUT",
            "scope": "day",
            "sequence": 1,
            "updated_at": 1.0,
            "poc": {
                "price": 100000.0,
                "player_id": 11,
                "label": "POC 100000",
                "holder": {"method": "total_volume", "state": "ok", "contracts": 80, "participation_pct": 66.7},
            },
            "val": {
                "price": 99990.0,
                "player_id": 22,
                "label": "VAL 99990",
                "holder": {
                    "method": "passive_buy_absorption",
                    "state": "ok",
                    "contracts": 44,
                    "participation_pct": 58.0,
                },
            },
            "vah": {
                "price": 100010.0,
                "player_id": 33,
                "label": "VAH 100010",
                "holder": {
                    "method": "passive_sell_absorption",
                    "state": "ok",
                    "contracts": 39,
                    "participation_pct": 55.0,
                },
            },
            "levels": [
                {"price": 100010.0, "total_vol": 80, "bid_vol": 40, "ask_vol": 40, "pct_of_max": 0.66},
                {"price": 100000.0, "total_vol": 120, "bid_vol": 60, "ask_vol": 60, "pct_of_max": 1.0},
                {"price": 99990.0, "total_vol": 70, "bid_vol": 35, "ask_vol": 35, "pct_of_max": 0.58},
            ],
            "top_player_avg_lines": [],
            "display": {
                "overlay_enabled": True,
                "poc_visible": True,
                "val_vah_visible": True,
                "labels_visible": True,
                "histogram_visible": True,
                "top_avg_visible": True,
            },
            "health": {
                "data_status": "ok",
                "axis_stale_ms": 0,
                "last_trade_age_ms": 0,
                "ocr_confidence": 0.83,
            },
        }

    def test_vp_overlay_debug_and_last_roundtrip(self) -> None:
        res = self.client.post("/api/vp-overlay/demo")
        self.assertEqual(res.status_code, 200)

        debug_res = self.client.get("/api/vp-overlay/debug", params={"symbol": "WINFUT"})
        self.assertEqual(debug_res.status_code, 200)
        debug_body = debug_res.json()
        self.assertTrue(debug_body["ok"])
        self.assertEqual(debug_body["symbol"], "WINFUT")
        self.assertEqual(debug_body["last_vp_overlay"]["raw_ticker"], "WINFUT · BMF")
        self.assertIn("last_overlay_publish_age_ms", debug_body)
        self.assertIn("last_overlay_publish_age_sec", debug_body)
        self.assertIn(debug_body["consolidator"]["overlay_age_state"], {"fresh", "stale", "missing"})
        self.assertIn("consolidator", debug_body)
        self.assertIn("last_vp_overlay", debug_body)
        self.assertEqual(debug_body["last_vp_overlay"]["symbol"], "WINFUT")

        last_res = self.client.get("/api/vp-overlay/last", params={"symbol": "WINFUT"})
        self.assertEqual(last_res.status_code, 200)
        last_body = last_res.json()
        self.assertTrue(last_body["ok"])
        self.assertEqual(last_body["symbol"], "WINFUT")
        self.assertEqual(last_body["snapshot"]["type"], "vp_overlay")
        self.assertEqual(last_body["snapshot"]["raw_ticker"], "WINFUT · BMF")

        health_res = self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        health_body = health_res.json()
        self.assertIn("vp_overlay_emit_count", health_body)
        self.assertIn("vp_overlay_skipped_same_hash", health_body)
        self.assertIn("vp_overlay_vp_cache_size", health_body)
        self.assertIn("vp_overlay_tape_cache_size", health_body)

    def test_vp_overlay_reset_clears_last_snapshot(self) -> None:
        self.assertEqual(self.client.post("/api/vp-overlay/demo").status_code, 200)
        self.assertIsNotNone(
            self.client.get("/api/vp-overlay/last", params={"symbol": "WINFUT"}).json()["snapshot"]
        )

        reset_res = self.client.post("/api/vp-overlay/reset", params={"symbol": "WINFUT"})
        self.assertEqual(reset_res.status_code, 200)
        self.assertTrue(reset_res.json()["ok"])

        last_res = self.client.get("/api/vp-overlay/last", params={"symbol": "WINFUT"})
        self.assertEqual(last_res.status_code, 200)
        self.assertIsNone(last_res.json()["snapshot"])

    def test_ocr_overlay_proxy_endpoints(self) -> None:
        async_mock = AsyncMock(return_value={"ok": True, "endpoint": "proxy"})
        with patch("websocket_server._ocr_overlay_proxy", async_mock):
            self.assertEqual(self.client.get("/api/ocr-overlay/status").status_code, 200)
            self.assertEqual(self.client.get("/api/ocr-overlay/debug").status_code, 200)
            self.assertEqual(self.client.post("/api/ocr-overlay/recalibrate").status_code, 200)
            self.assertEqual(self.client.post("/api/ocr-overlay/freeze").status_code, 200)
            self.assertEqual(self.client.post("/api/ocr-overlay/unfreeze").status_code, 200)
            self.assertEqual(
                self.client.post(
                    "/api/ocr-overlay/manual-calibration",
                    json={"points": [{"value": 100, "y_screen": 200}, {"value": 120, "y_screen": 100}]},
                ).status_code,
                200,
            )

    def test_ocr_overlay_manual_calibration_invalid_payload(self) -> None:
        response = self.client.post("/api/ocr-overlay/manual-calibration", json={"points": []})
        self.assertEqual(response.status_code, 400)
        body = response.json()["detail"]
        self.assertEqual(body["endpoint"], "/api/ocr-overlay/manual-calibration")
        self.assertEqual(body["error_code"], "OCR_INVALID_PAYLOAD")
        self.assertIn("ts", body)
        self.assertIn("details", body)

    def test_ocr_overlay_proxy_invalid_payload_error_shape(self) -> None:
        exc = urllib.error.HTTPError(
            url="http://127.0.0.1:5558/api/ocr-overlay/manual-calibration",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=None,
        )
        with patch("websocket_server._ocr_overlay_proxy_sync", side_effect=exc):
            response = self.client.post(
                "/api/ocr-overlay/manual-calibration",
                json={"points": [{"value": 100, "y_screen": 200}, {"value": 120, "y_screen": 100}]},
            )
        self.assertEqual(response.status_code, 400)
        body = response.json()["detail"]
        self.assertEqual(body["endpoint"], "/api/ocr-overlay/manual-calibration")
        self.assertEqual(body["error_code"], "OCR_INVALID_PAYLOAD")
        self.assertIn("ts", body)

    def test_ocr_overlay_proxy_inconsistent_state_error_shape(self) -> None:
        exc = urllib.error.HTTPError(
            url="http://127.0.0.1:5558/api/ocr-overlay/freeze",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=None,
        )
        with patch("websocket_server._ocr_overlay_proxy_sync", side_effect=exc):
            response = self.client.post("/api/ocr-overlay/freeze")
        self.assertEqual(response.status_code, 409)
        body = response.json()["detail"]
        self.assertEqual(body["endpoint"], "/api/ocr-overlay/freeze")
        self.assertEqual(body["error_code"], "OCR_INCONSISTENT_STATE")
        self.assertIn("ts", body)

    def test_ocr_overlay_proxy_timeout_error_shape(self) -> None:
        with patch("websocket_server._ocr_overlay_proxy_sync", side_effect=TimeoutError("timed out waiting")):
            response = self.client.get("/api/ocr-overlay/status")
        self.assertEqual(response.status_code, 504)
        body = response.json()["detail"]
        self.assertEqual(body["endpoint"], "/api/ocr-overlay/status")
        self.assertEqual(body["error_code"], "OCR_DOWNSTREAM_TIMEOUT")
        self.assertIn("ts", body)


if __name__ == "__main__":
    unittest.main()
