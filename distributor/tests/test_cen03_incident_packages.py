from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "cen03_incident_packages.py"
    spec = importlib.util.spec_from_file_location("cen03_incident_packages", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = _load_module()


class TestCen03IncidentPackages(unittest.TestCase):
    def test_build_incident_package_generates_required_shape(self) -> None:
        package = helper.build_incident_package(
            incident_id="CEN-03-INC-HELPER-001",
            symptom="ocr degradation",
            suspected_root_cause="contrast drop",
            action_taken="recover signal",
            result="pass",
            transitions=["STABLE->FROZEN|RECALIBRATING", "FROZEN|RECALIBRATING->STABLE"],
            evidence_refs=["artifact://one", "artifact://two", "artifact://three"],
            channel_payload={
                "hud": {"expected": "axis_status=FROZEN", "observed": "axis_status=FROZEN", "evidence_ref": "artifact://hud"},
                "status_endpoint": {"expected": "bad_frames>0", "observed": "bad_frames=4", "evidence_ref": "artifact://status"},
                "trace_jsonl": {
                    "expected": "transition to STABLE after degradation",
                    "observed": "transition to STABLE after degradation",
                    "evidence_ref": "artifact://trace",
                },
            },
        )
        report = helper.validate_cen03_incident_packages({"scenarios": {"CEN-03": {"incident_packages": [package]}}})
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_incidents"], 1)

    def test_main_writes_incident_packages_and_field_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "incident_packages.json"
            field_report_out = Path(tmp) / "field_report.json"
            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "cen03_incident_packages.py",
                    "--incident-id",
                    "CEN-03-INC-HELPER-002",
                    "--symptom",
                    "degradation under load",
                    "--suspected-root-cause",
                    "ocr occlusion",
                    "--action-taken",
                    "fallback and recover",
                    "--transition",
                    "STABLE->FROZEN|RECALIBRATING",
                    "--transition",
                    "FROZEN|RECALIBRATING->STABLE",
                    "--evidence-ref",
                    "artifact://inc2-a",
                    "--evidence-ref",
                    "artifact://inc2-b",
                    "--evidence-ref",
                    "artifact://inc2-c",
                    "--hud-expected",
                    "axis_status should freeze",
                    "--hud-observed",
                    "axis_status=FROZEN",
                    "--hud-evidence-ref",
                    "artifact://inc2-hud",
                    "--status-expected",
                    "bad_frames rises then falls",
                    "--status-observed",
                    "bad_frames=6 then 0",
                    "--status-evidence-ref",
                    "artifact://inc2-status",
                    "--trace-expected",
                    "transition to stable logged",
                    "--trace-observed",
                    "transition to stable logged",
                    "--trace-evidence-ref",
                    "artifact://inc2-trace",
                    "--out",
                    str(out),
                    "--field-report-out",
                    str(field_report_out),
                    "--strict",
                ]
                code = helper.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(code, 0)
            package_payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("incident_packages", package_payload)
            self.assertEqual(package_payload["incident_packages"][0]["incident_id"], "CEN-03-INC-HELPER-002")
            field_payload = json.loads(field_report_out.read_text(encoding="utf-8"))
            report = helper.validate_cen03_incident_packages(field_payload)
            self.assertTrue(report["ok"])

    def test_build_incident_evidence_index_returns_indexed_channels(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-INDEX-001",
                            "expected_vs_observed_by_channel": {
                                "hud": {"expected": "e", "observed": "o", "evidence_ref": "artifact://hud"},
                                "status_endpoint": {"expected": "e", "observed": "o", "evidence_ref": "artifact://status"},
                                "trace_jsonl": {"expected": "e", "observed": "o", "evidence_ref": "artifact://trace"},
                            },
                            "observed_state_transitions": [
                                "STABLE->FROZEN|RECALIBRATING",
                                "FROZEN|RECALIBRATING->STABLE",
                            ],
                            "evidence_ref": ["artifact://a", "artifact://b", "artifact://c"],
                        }
                    ]
                }
            }
        }
        report = helper.build_incident_evidence_index(payload)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_incidents"], 1)
        self.assertIn("CEN-03-INC-INDEX-001", report["index"])
        row = report["index"]["CEN-03-INC-INDEX-001"]
        self.assertEqual(sorted(row["channels_with_evidence"]), ["hud", "status_endpoint", "trace_jsonl"])

    def test_build_incident_evidence_index_rejects_duplicate_incident_id(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {"incident_id": "CEN-03-INC-DUP", "expected_vs_observed_by_channel": {}},
                        {"incident_id": "CEN-03-INC-DUP", "expected_vs_observed_by_channel": {}},
                    ]
                }
            }
        }
        report = helper.build_incident_evidence_index(payload)
        self.assertFalse(report["ok"])
        self.assertIn("CEN-03-INC-DUP:duplicated_incident_id", report["errors"])
        self.assertEqual(report["checked_incidents"], 1)


if __name__ == "__main__":
    unittest.main()
