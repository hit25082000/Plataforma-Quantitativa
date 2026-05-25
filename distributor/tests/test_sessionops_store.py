from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from sessionops_contract import build_event, new_session_context
from sessionops_store import SessionOpsStore


class TestSessionOpsStore(unittest.TestCase):
    def test_upsert_and_query(self) -> None:
        td = Path(tempfile.mkdtemp(prefix="sessionops-store-"))
        store = SessionOpsStore(td / "session_registry.db")
        ctx = new_session_context(component="distributor", build="test")
        ev1 = build_event(ctx=ctx, event_type="session_start", stage="bootstrap", status="started")
        ev2 = build_event(
            ctx=ctx,
            event_type="incident",
            stage="gate",
            status="failed",
            error_code="overlay_ws_stale",
            payload={"reason": "no_messages"},
        )
        store.upsert_event(ev1)
        store.upsert_event(ev2)

        sessions = store.list_sessions(limit=10)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], ctx.session_id)

        session = store.get_session(ctx.session_id)
        assert session is not None
        self.assertGreaterEqual(len(session["events"]), 2)

        incidents = store.list_incidents(limit=10)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["error_code"], "overlay_ws_stale")


if __name__ == "__main__":
    unittest.main()
