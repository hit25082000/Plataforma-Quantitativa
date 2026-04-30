from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "check_cen04_monitor_dpi_matrix.py"
    spec = importlib.util.spec_from_file_location("check_cen04_monitor_dpi_matrix", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_module()


def _valid_payload() -> dict:
    return {
        "scenarios": {
            "CEN-04": {
                "monitor_dpi_matrix": [
                    {
                        "monitor_id": "monitor-1",
                        "dpi_percent": 100,
                        "transition": "baseline-open",
                        "bounds_ok": True,
                        "overlay_ok": True,
                        "drift_px": 1.0,
                        "evidence_ref": "artifact://m1",
                    },
                    {
                        "monitor_id": "monitor-2",
                        "dpi_percent": 125,
                        "transition": "move-to-monitor",
                        "bounds_ok": True,
                        "overlay_ok": True,
                        "drift_px": 1.1,
                        "evidence_ref": "artifact://m2",
                    },
                    {
                        "monitor_id": "monitor-3",
                        "dpi_percent": 150,
                        "transition": "move-to-monitor",
                        "bounds_ok": True,
                        "overlay_ok": True,
                        "drift_px": 1.2,
                        "evidence_ref": "artifact://m3",
                    },
                ],
                "drift_steps": [
                    {"step_id": "open_window_on_baseline_monitor", "monitor_id": "monitor-1", "dpi_percent": 100, "axis_status_before": "STABLE", "axis_status_after": "STABLE", "drift_px": 1.0, "evidence_ref": "artifact://s1"},
                    {"step_id": "move_window_to_next_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "STABLE", "axis_status_after": "RECALIBRATING", "drift_px": 1.0, "evidence_ref": "artifact://s2"},
                    {"step_id": "minimize_window_on_target_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "RECALIBRATING", "axis_status_after": "FROZEN", "drift_px": 1.0, "evidence_ref": "artifact://s3"},
                    {"step_id": "restore_window_on_target_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "FROZEN", "axis_status_after": "RECALIBRATING", "drift_px": 1.0, "evidence_ref": "artifact://s4"},
                    {"step_id": "move_window_back_to_baseline_monitor", "monitor_id": "monitor-3", "dpi_percent": 150, "axis_status_before": "RECALIBRATING", "axis_status_after": "STABLE", "drift_px": 1.0, "evidence_ref": "artifact://s5"},
                ],
            }
        }
    }


class TestCheckCen04MonitorDpiMatrix(unittest.TestCase):
    def test_validate_passes_with_complete_matrix_and_steps(self) -> None:
        report = checker.validate_cen04_field_matrix(_valid_payload())
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_rows"], 3)
        self.assertEqual(report["checked_steps"], 5)
        self.assertEqual(report["issues"], [])

    def test_validate_returns_actionable_issues(self) -> None:
        payload = _valid_payload()
        payload["scenarios"]["CEN-04"]["monitor_dpi_matrix"][1]["dpi_percent"] = 100
        payload["scenarios"]["CEN-04"]["monitor_dpi_matrix"][1]["drift_px"] = 9.9
        payload["scenarios"]["CEN-04"]["monitor_dpi_matrix"][1]["evidence_ref"] = ""
        payload["scenarios"]["CEN-04"]["drift_steps"] = [{"step_id": "open_window_on_baseline_monitor"}]
        report = checker.validate_cen04_field_matrix(payload)
        self.assertFalse(report["ok"])
        self.assertTrue(any("|acao:" in issue for issue in report["issues"]))
        joined = ",".join(report["issues"])
        self.assertIn("CEN-04:matrix_duplicated_dpi:100", joined)
        self.assertIn("CEN-04:matrix_drift_gt_3px:1", joined)
        self.assertIn("CEN-04:step_missing_required:move_window_to_next_monitor", joined)

    def test_main_writes_actionable_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            field_report = root / "field-report.json"
            out_dir = root / "out"
            payload = _valid_payload()
            payload["scenarios"]["CEN-04"]["drift_steps"] = []
            field_report.write_text(json.dumps(payload), encoding="utf-8")

            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "check_cen04_monitor_dpi_matrix.py",
                    "--strict",
                    "--field-report",
                    str(field_report),
                    "--out-dir",
                    str(out_dir),
                ]
                exit_code = checker.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(exit_code, 2)
            summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")
            summary_manifest = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertIn("## Acao do operador", summary_md)
            self.assertIn("|acao:", summary_md)
            self.assertFalse(summary_manifest["ok"])
            self.assertIn("issues", summary_manifest)


if __name__ == "__main__":
    unittest.main()
