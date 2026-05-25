from __future__ import annotations

import sys
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from sessionops_contract import (
    SESSIONOPS_CONTRACT_VERSION,
    build_event,
    coerce_legacy_ocr_trace_row,
    new_session_context,
)


class TestSessionOpsContract(unittest.TestCase):
    def test_build_event_contains_required_envelope(self) -> None:
        ctx = new_session_context(component="distributor", build="test-build")
        event = build_event(
            ctx=ctx,
            event_type="session_start",
            stage="bootstrap",
            status="started",
            metrics={"x": 1},
        )
        self.assertEqual(event["sessionops_contract_version"], SESSIONOPS_CONTRACT_VERSION)
        for key in (
            "event_id",
            "session_id",
            "run_id",
            "component",
            "stage",
            "status",
            "ts_utc",
            "host",
            "pid",
            "build",
            "asset",
            "monitor_dpi",
            "error_code",
            "metrics",
            "artifacts",
        ):
            self.assertIn(key, event)

    def test_legacy_ocr_row_is_coerced(self) -> None:
        ctx = new_session_context(component="ocr", build="legacy")
        row = {
            "event": "frame",
            "seq": 10,
            "status": "ok",
            "labels": [{"value": 1, "y_screen": 2}],
            "axis_fit": {"residual_px": 0.8, "confidence": 0.9},
            "rendered_lines": [{"label": "POC"}],
        }
        ev = coerce_legacy_ocr_trace_row(row, default_ctx=ctx)
        self.assertEqual(ev["event_type"], "axis_update")
        self.assertEqual(ev["metrics"]["seq"], 10)
        self.assertEqual(ev["metrics"]["labels"], 1)


if __name__ == "__main__":
    unittest.main()
