from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

import ocr_overlay_audit


class TestOcrOverlayAudit(unittest.TestCase):
    def test_build_frame_record_contains_axis_and_lines(self) -> None:
        row = ocr_overlay_audit.build_frame_record(
            session_id="s1",
            seq=10,
            status="ok",
            labels=[{"value": 185250.0, "y_screen": 120.0}],
            axis_fit={"slope": -0.25, "intercept": 186000.0, "residual_px": 1.2, "confidence": 0.77},
            axis={"slope": -0.26, "intercept": 186010.0},
            lines=[{"label": "POC", "value": 185200.0, "y_screen": 140, "status": "visible"}],
        )
        self.assertEqual(row["event"], "frame")
        self.assertEqual(row["event_id"], "frame")
        self.assertEqual(row["session_id"], "s1")
        self.assertEqual(row["frame_seq"], 10)
        self.assertIn("timestamp_utc", row)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["axis_fit"]["slope"], -0.25)
        self.assertEqual(row["axis_fit"]["intercept"], 186000.0)
        self.assertEqual(row["axis_fit"]["residual_px"], 1.2)
        self.assertEqual(row["axis_fit"]["confidence"], 0.77)
        self.assertEqual(row["rendered_lines"][0]["y_screen"], 140)
        self.assertIn("render_indicators", row)
        self.assertEqual(row["render_indicators"]["line_count_total"], 1)

    def test_audit_trail_writes_session_metadata_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ocr_overlay_trace.jsonl"
            trail = ocr_overlay_audit.OcrOverlayAuditTrail(
                trace_path=str(path),
                session_metadata={"event": "session_start", "session_id": "s1"},
            )
            trail.append({"event": "frame", "seq": 1})
            trail.append({"event": "frame", "seq": 2})

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(rows[0]["event"], "session_start")
        self.assertEqual(rows[0]["event_id"], "session_start")
        self.assertEqual(rows[1]["seq"], 1)
        self.assertEqual(rows[2]["seq"], 2)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["session_id"], "s1")
        self.assertEqual(rows[1]["event_id"], "frame")
        self.assertIn("timestamp_utc", rows[1])
        self.assertIn("render_indicators", rows[1])
        self.assertIn("status_transition", rows[1])

    def test_audit_trail_computes_status_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ocr_overlay_trace.jsonl"
            trail = ocr_overlay_audit.OcrOverlayAuditTrail(
                trace_path=str(path),
                session_metadata={"event": "session_start", "session_id": "s1"},
            )
            trail.append({"event": "frame", "seq": 1, "status": "STABLE"})
            trail.append({"event": "frame", "seq": 2, "status": "SUSPECT"})
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

        transition = rows[2]["status_transition"]
        self.assertEqual(transition["from"], "STABLE")
        self.assertEqual(transition["to"], "SUSPECT")
        self.assertTrue(transition["changed"])

    def test_audit_trail_completes_partial_status_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ocr_overlay_trace.jsonl"
            trail = ocr_overlay_audit.OcrOverlayAuditTrail(
                trace_path=str(path),
                session_metadata={"event": "session_start", "session_id": "s1"},
            )
            trail.append({"event": "frame", "seq": 1, "status": "STABLE"})
            trail.append({"event": "frame", "seq": 2, "status": "FROZEN", "status_transition": {"to": "FROZEN"}})
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

        transition = rows[2]["status_transition"]
        self.assertEqual(transition["from"], "STABLE")
        self.assertEqual(transition["to"], "FROZEN")
        self.assertTrue(transition["changed"])

    def test_summarize_trace_rows_basic(self) -> None:
        rows = [
            {"event": "session_start", "session_id": "s1"},
            {"event": "frame", "status": "ok", "rendered_lines": [1, 2], "axis_fit": {"residual_px": 1.0, "confidence": 0.8}},
            {"event": "frame", "status": "ocr_axis_fit_failed", "rendered_lines": [], "axis_fit": {"residual_px": 2.0, "confidence": 0.2}},
        ]
        summary = ocr_overlay_audit.summarize_trace_rows(rows)
        self.assertEqual(summary["total_frames"], 2)
        self.assertEqual(summary["ok_frames"], 1)
        self.assertEqual(summary["ok_ratio"], 0.5)
        self.assertEqual(summary["avg_lines"], 1.0)
        self.assertEqual(summary["avg_residual_px"], 1.5)
        self.assertEqual(summary["avg_confidence"], 0.5)


if __name__ == "__main__":
    unittest.main()
