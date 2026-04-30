from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from connection_manager import ConnectionManager
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


class _FakeRouter:
    def __init__(self) -> None:
        self.frames: list[str] = []

    async def route(self, raw: str) -> None:
        self.frames.append(raw)


class TestVpTapeWebsocketEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.main_manager = ConnectionManager()
        self.vp_manager = ConnectionManager()
        websocket_server.init_app(
            self.main_manager,
            _FakeConsumer(),
            volume_profile_connection_manager=self.vp_manager,
        )
        self.client = TestClient(websocket_server.create_app())

    def test_ws_volume_profile_uses_dedicated_manager(self) -> None:
        self.assertEqual(len(self.main_manager.active), 0)
        self.assertEqual(len(self.vp_manager.active), 0)
        with self.client.websocket_connect("/ws/volume-profile") as ws:
            self.assertEqual(len(self.main_manager.active), 0)
            self.assertEqual(len(self.vp_manager.active), 1)
            ws.send_text("ping")
        self.assertEqual(len(self.vp_manager.active), 0)

    def test_ws_tape_intelligence_uses_dedicated_manager(self) -> None:
        self.assertEqual(len(self.main_manager.active), 0)
        self.assertEqual(len(self.vp_manager.active), 0)
        with self.client.websocket_connect("/ws/tape-intelligence") as ws:
            self.assertEqual(len(self.main_manager.active), 0)
            self.assertEqual(len(self.vp_manager.active), 1)
            ws.send_text("ping")
        self.assertEqual(len(self.vp_manager.active), 0)

    def test_vp_sato_demo_posts_synthetic_vp_and_tape(self) -> None:
        router = _FakeRouter()
        websocket_server.init_app(
            self.main_manager,
            _FakeConsumer(),
            router=router,
            volume_profile_connection_manager=self.vp_manager,
        )
        client = TestClient(websocket_server.create_app())

        res = client.post(
            "/api/vp-sato/demo",
            json={"ticker": "DEMO", "base_price": 100000, "price_step": 5, "levels": 40},
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["levels"], 40)
        self.assertEqual(len(router.frames), 2)
        self.assertIn('"type":"volume_profile"', router.frames[0])
        self.assertIn('"type":"tape_intelligence"', router.frames[1])


if __name__ == "__main__":
    unittest.main()
