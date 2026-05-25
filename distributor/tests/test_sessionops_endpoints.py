from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from connection_manager import ConnectionManager
from message_router import MessageRouter
from startup_state import startup_state
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


class TestSessionOpsEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        startup_state.reset(ipc_mode="zmq")
        manager = ConnectionManager()
        vp_tape_manager = ConnectionManager()
        vp_overlay_manager = ConnectionManager()
        router = MessageRouter(
            manager,
            throttle_ms=0,
            vp_overlay_manager=vp_overlay_manager,
            vp_overlay_consolidator=VpOverlayConsolidator(publish_interval_ms=0),
        )
        websocket_server.init_app(
            manager,
            _FakeConsumer(),
            router=router,
            volume_profile_connection_manager=vp_tape_manager,
            vp_overlay_connection_manager=vp_overlay_manager,
        )
        self.client = TestClient(websocket_server.create_app())

    def test_sessionops_core_endpoints(self) -> None:
        sessions = self.client.get("/api/sessionops/sessions")
        self.assertEqual(sessions.status_code, 200)
        body = sessions.json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(len(body["sessions"]), 1)
        session_id = body["sessions"][0]["session_id"]

        one = self.client.get(f"/api/sessionops/sessions/{session_id}")
        self.assertEqual(one.status_code, 200)
        self.assertTrue(one.json()["ok"])

        incidents = self.client.get("/api/sessionops/incidents")
        self.assertEqual(incidents.status_code, 200)
        self.assertTrue(incidents.json()["ok"])

        timeline = self.client.get("/api/sessionops/timeline")
        self.assertEqual(timeline.status_code, 200)
        self.assertTrue(timeline.json()["ok"])

        snap = self.client.get("/api/sessionops/agent-snapshot")
        self.assertEqual(snap.status_code, 200)
        snap_body = snap.json()
        self.assertTrue(snap_body["ok"])
        self.assertIn("recommended_next_action", snap_body)

    def test_sessionops_html_endpoint(self) -> None:
        response = self.client.get("/sessionops")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SessionOps Agent Mirror", response.text)


if __name__ == "__main__":
    unittest.main()
