from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


def _load_runner_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_ovr_stab_qa_evidence.py"
    spec = importlib.util.spec_from_file_location("run_ovr_stab_qa_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner_module()


class TestOcrOverlayTraceContract(unittest.TestCase):
    def test_trace_schema_declares_event_variants(self) -> None:
        schema = json.loads(runner.TRACE_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("oneOf", schema)
        self.assertGreaterEqual(len(schema["oneOf"]), 2)
        self.assertIn("$defs", schema)
        self.assertIn("session_start_event", schema["$defs"])
        self.assertIn("frame_event", schema["$defs"])

    def test_trace_fixture_contains_session_and_frame_events(self) -> None:
        rows = [
            json.loads(line)
            for line in runner.TRACE_FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        events = {str(row.get("event")) for row in rows}
        self.assertIn("session_start", events)
        self.assertIn("frame", events)

    def test_validate_trace_schema_fixture_contract(self) -> None:
        ok, errors, report = runner.validate_trace_schema_fixture_contract()
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(int(report.get("rows_checked", 0)), 2)
        self.assertGreaterEqual(int(report.get("frame_rows", 0)), 1)
        self.assertGreaterEqual(int(report.get("session_rows", 0)), 1)

    def test_trace_required_fields_by_event_includes_core_contract(self) -> None:
        by_event = runner.TRACE_REQUIRED_BY_EVENT
        self.assertIn("session_start", by_event)
        self.assertIn("frame", by_event)
        self.assertIn("event_id", by_event["session_start"])
        self.assertIn("frame_seq", by_event["frame"])
        self.assertIn("status_transition", by_event["frame"])


if __name__ == "__main__":
    unittest.main()
