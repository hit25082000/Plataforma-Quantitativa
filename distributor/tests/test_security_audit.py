"""Tests for shared security audit writer."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import security_audit


class TestSecurityAudit(unittest.TestCase):
    def setUp(self) -> None:
        security_audit.reset_security_audit_metrics()

    def test_write_appends_source_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "audit.jsonl"
            security_audit.write_security_audit(
                str(target),
                {"event": "unit_test_event", "status": "ok"},
                source="unit_test",
            )

            lines = [line.strip() for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["event"], "unit_test_event")
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["source"], "unit_test")
            self.assertIn("ts_utc", record)

            metrics = security_audit.security_audit_metrics()
            self.assertEqual(metrics["writes_ok"], 1)
            self.assertEqual(metrics["writes_failed"], 0)
            self.assertEqual(metrics["source_counts"].get("unit_test"), 1)
            self.assertEqual(metrics["status_counts"].get("unit_test:ok"), 1)

    def test_retention_prunes_old_rotated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "audit.jsonl"
            old_file = Path(tmp) / "audit-20000101.jsonl"
            new_file = Path(tmp) / "audit-20990101.jsonl"
            old_file.write_text('{"event":"old"}\n', encoding="utf-8")
            new_file.write_text('{"event":"new"}\n', encoding="utf-8")

            old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
            new_ts = datetime.now(timezone.utc).timestamp()
            os.utime(old_file, (old_ts, old_ts))
            os.utime(new_file, (new_ts, new_ts))

            security_audit.write_security_audit(
                str(base),
                {"event": "unit_test_event", "status": "ok"},
                source="unit_test",
                env={
                    "SECURITY_AUDIT_RETENTION_DAYS": "7",
                    "SECURITY_AUDIT_PRUNE_INTERVAL_S": "0",
                },
            )

            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
            self.assertTrue(base.exists())

            metrics = security_audit.security_audit_metrics()
            self.assertGreaterEqual(metrics["pruned_files"], 1)
            self.assertEqual(metrics["prune_errors"], 0)
            self.assertTrue(metrics["last_prune_ts_utc"])

    def test_daily_rotation_uses_dated_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "agent007_audit.jsonl"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            rotated = Path(tmp) / f"agent007_audit-{stamp}.jsonl"

            security_audit.write_security_audit(
                str(base),
                {"event": "rotated", "status": "ok"},
                source="unit_test",
                env={"SECURITY_AUDIT_DAILY_ROTATE": "1"},
            )

            self.assertFalse(base.exists())
            self.assertTrue(rotated.exists())


if __name__ == "__main__":
    unittest.main()
