from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import websocket_server


class TestVoiceSessionProxy(unittest.TestCase):
    def setUp(self) -> None:
        websocket_server.voice_session_store.clear()
        self._orig_create_realtime_session = websocket_server.create_realtime_session
        websocket_server.create_realtime_session = lambda: {
            "ok": True,
            "ws_url": "wss://example.invalid/ws?key=test",
            "setup_message": {"setup": {"model": "models/test"}},
            "max_duration_s": 600,
            "provider": "gemini",
        }
        self.client = TestClient(websocket_server.create_app())

    def tearDown(self) -> None:
        websocket_server.create_realtime_session = self._orig_create_realtime_session
        websocket_server.voice_session_store.clear()

    def test_session_endpoint_returns_local_proxy_ws_url(self) -> None:
        response = self.client.post("/api/voice/session")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["transport"], "proxy")
        self.assertTrue(data["ws_url"].startswith("ws://127.0.0.1:8000/api/voice/ws/"))
        session_id = data["session_id"]
        self.assertIn(session_id, websocket_server.voice_session_store)


if __name__ == "__main__":
    unittest.main()
