from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "verify_ovr_stab_g8_readiness.py"
    spec = importlib.util.spec_from_file_location("verify_ovr_stab_g8_readiness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module()


class TestVerifyOvrStabG8Readiness(unittest.TestCase):
    def test_scenario_result_marks_local_gap_when_not_covered(self) -> None:
        qa_manifest = {"ovr_status": {"OVR-STAB-QA-04": {"state": "not-covered"}}}
        row = validator._scenario_result(
            {"id": "CEN-04", "ovr_id": "OVR-STAB-QA-04", "title": "Multi-monitor DPI"},
            qa_manifest=qa_manifest,
            stress_manifest={},
            field_scenarios={},
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(row["local_validation"]["pass"])
        self.assertTrue(any(gap["gap_id"] == "GAP-CEN-04-LOCAL" for gap in row["gaps"]))

    def test_scenario_result_marks_cen05_local_fail_when_stress_gate_fails(self) -> None:
        stress_manifest = {"gate": {"ok": False, "failures": ["publish_rate_floor_ratio=0.41 < 0.75"]}}
        row = validator._scenario_result(
            {"id": "CEN-05", "ovr_id": "OVR-STAB-QA-05", "title": "Carga real"},
            qa_manifest={},
            stress_manifest=stress_manifest,
            field_scenarios={},
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertTrue(any(gap["gap_id"] == "GAP-CEN-05-LOCAL" for gap in row["gaps"]))

    def test_scenario_result_passes_when_local_and_field_are_ready(self) -> None:
        qa_manifest = {"ovr_status": {"OVR-STAB-QA-01": {"state": "partial-done"}}}
        field_scenarios = {"CEN-01": {"pass": True, "evidence_ref": "artifact://cen01"}}
        row = validator._scenario_result(
            {"id": "CEN-01", "ovr_id": "OVR-STAB-QA-01", "title": "Parado 60s"},
            qa_manifest=qa_manifest,
            stress_manifest={},
            field_scenarios=field_scenarios,
            field_report_issues={},
        )
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["classification"], "CONFIRMED_READY")
        self.assertTrue(row["field_validation"]["pass"])
        self.assertEqual(row["field_validation"]["evidence_ref"], "artifact://cen01")

    def test_scenario_result_flags_false_positive_risk(self) -> None:
        qa_manifest = {"ovr_status": {"OVR-STAB-QA-02": {"state": "partial-done"}}}
        row = validator._scenario_result(
            {"id": "CEN-02", "ovr_id": "OVR-STAB-QA-02", "title": "Zoom/escala"},
            qa_manifest=qa_manifest,
            stress_manifest={},
            field_scenarios={"CEN-02": {"pass": False}},
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["classification"], "FALSE_POSITIVE_RISK")
        self.assertIn("campo nao confirmou", row["diagnosis"])

    def test_scenario_result_flags_false_negative_risk(self) -> None:
        qa_manifest = {"ovr_status": {"OVR-STAB-QA-03": {"state": "missing"}}}
        row = validator._scenario_result(
            {"id": "CEN-03", "ovr_id": "OVR-STAB-QA-03", "title": "OCR degradado"},
            qa_manifest=qa_manifest,
            stress_manifest={},
            field_scenarios={
                "CEN-03": {
                    "pass": True,
                    "evidence_ref": "artifact://cen03",
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-OK-001",
                            "expected_vs_observed_by_channel": {
                                "hud": {
                                    "expected": "axis_status=FROZEN",
                                    "observed": "axis_status=FROZEN",
                                    "evidence_ref": "artifact://cen03-hud",
                                },
                                "status_endpoint": {
                                    "expected": "bad_frames increase during degradation",
                                    "observed": "bad_frames=5 during degradation",
                                    "evidence_ref": "artifact://cen03-status",
                                },
                                "trace_jsonl": {
                                    "expected": "recovery transition to STABLE",
                                    "observed": "recovery transition to STABLE",
                                    "evidence_ref": "artifact://cen03-trace",
                                },
                            },
                            "observed_state_transitions": [
                                "STABLE->FROZEN|RECALIBRATING",
                                "FROZEN|RECALIBRATING->STABLE",
                            ],
                            "evidence_ref": [
                                "artifact://cen03-a",
                                "artifact://cen03-b",
                                "artifact://cen03-c",
                            ],
                        }
                    ],
                }
            },
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["classification"], "FALSE_NEGATIVE_RISK")
        self.assertIn("auditar gate", row["next_action"])

    def test_scenario_result_cen03_requires_incident_package_contract(self) -> None:
        row = validator._scenario_result(
            {"id": "CEN-03", "ovr_id": "OVR-STAB-QA-03", "title": "OCR degradado"},
            qa_manifest={"ovr_status": {"OVR-STAB-QA-03": {"state": "partial-done"}}},
            stress_manifest={},
            field_scenarios={
                "CEN-03": {
                    "pass": True,
                    "evidence_ref": "artifact://cen03",
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-INVALID",
                            "expected_vs_observed_by_channel": {
                                "hud": {"expected": "freeze", "observed": "freeze", "evidence_ref": "artifact://hud"}
                            },
                            "observed_state_transitions": ["STABLE->FROZEN|RECALIBRATING"],
                            "evidence_ref": ["artifact://single"],
                        }
                    ],
                }
            },
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("missing_channel:status_endpoint", row["field_validation"]["details"])
        self.assertTrue(any(gap["gap_id"] == "GAP-CEN-03-FIELD" for gap in row["gaps"]))
        self.assertIn("CEN-03-INC-INVALID", row["field_validation"]["incident_evidence_index"])

    def test_load_field_report_handles_invalid_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.json"
            path.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
            loaded, issues, global_issues = validator._load_field_report(path)
            self.assertEqual(loaded, {})
            self.assertEqual(issues, {})
            self.assertEqual(global_issues, [])

    def test_load_field_report_accepts_list_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.json"
            path.write_text(
                json.dumps(
                    {
                        "scenarios": [
                            {
                                "scenario_id": "CEN-02",
                                "result": "pass",
                                "evidence_refs": {"trace_jsonl": "artifact://cen02-trace"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            loaded, issues, global_issues = validator._load_field_report(path)
            self.assertTrue(loaded["CEN-02"]["pass"])
            self.assertEqual(loaded["CEN-02"]["evidence_ref"], "artifact://cen02-trace")
            self.assertIn("CEN-02", issues)
            self.assertEqual(global_issues, [])

    def test_scenario_result_reports_field_validation_issue(self) -> None:
        row = validator._scenario_result(
            {"id": "CEN-02", "ovr_id": "OVR-STAB-QA-02", "title": "Zoom/escala"},
            qa_manifest={"ovr_status": {"OVR-STAB-QA-02": {"state": "partial-done"}}},
            stress_manifest={},
            field_scenarios={"CEN-02": {"pass": False, "evidence_ref": ""}},
            field_report_issues={"CEN-02": ["missing_evidence_ref"]},
        )
        self.assertEqual(row["classification"], "FALSE_POSITIVE_RISK")
        self.assertEqual(row["field_validation"]["details"], "missing_evidence_ref")
        self.assertIn("field-report invalido", row["gaps"][0]["reason"])

    def test_load_field_report_validates_cen02_transition_evidence_by_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.json"
            path.write_text(
                json.dumps(
                    {
                        "scenarios": {
                            "CEN-02": {
                                "result": "pass",
                                "evidence_ref": "artifact://cen02",
                                "transition_evidence": [
                                    {
                                        "transition_state": "SUSPECT",
                                        "observed": True,
                                        "screenshot_ref": "artifact://suspect.png",
                                        "trace_ref": "artifact://suspect.jsonl",
                                        "status_endpoint_ref": "artifact://suspect.status.txt",
                                        "expected_vs_observed": "ok",
                                        "trigger_action": "zoom-in",
                                        "observed_at_utc": "2026-04-30T14:10:00Z",
                                    }
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            _, issues, _ = validator._load_field_report(path)
            self.assertIn("CEN-02", issues)
            joined = ",".join(issues["CEN-02"])
            self.assertIn("CEN-02:FROZEN:missing_transition|acao:registrar evento FROZEN", joined)
            self.assertIn("CEN-02:RECALIBRATING:missing_transition|acao:registrar evento RECALIBRATING", joined)

    def test_load_field_report_accepts_complete_cen02_transition_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.json"
            path.write_text(
                json.dumps(
                    {
                        "scenarios": {
                            "CEN-02": {
                                "result": "pass",
                                "evidence_ref": "artifact://cen02",
                                "transition_evidence": [
                                    {
                                        "transition_state": "SUSPECT",
                                        "observed": True,
                                        "screenshot_ref": "artifact://suspect.png",
                                        "trace_ref": "artifact://suspect.jsonl",
                                        "status_endpoint_ref": "artifact://suspect.status.txt",
                                        "expected_vs_observed": "ok",
                                        "trigger_action": "zoom-in",
                                        "observed_at_utc": "2026-04-30T14:10:00Z",
                                    },
                                    {
                                        "transition_state": "FROZEN",
                                        "observed": True,
                                        "screenshot_ref": "artifact://frozen.png",
                                        "trace_ref": "artifact://frozen.jsonl",
                                        "status_endpoint_ref": "artifact://frozen.status.txt",
                                        "expected_vs_observed": "ok",
                                        "freeze_duration_ms": "3200",
                                        "observed_at_utc": "2026-04-30T14:10:05Z",
                                    },
                                    {
                                        "transition_state": "RECALIBRATING",
                                        "observed": True,
                                        "screenshot_ref": "artifact://recal.png",
                                        "trace_ref": "artifact://recal.jsonl",
                                        "status_endpoint_ref": "artifact://recal.status.txt",
                                        "expected_vs_observed": "ok",
                                        "stable_return_ref": "artifact://stable-return.png",
                                        "observed_at_utc": "2026-04-30T14:10:09Z",
                                    },
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            loaded, issues, global_issues = validator._load_field_report(path)
            self.assertEqual(global_issues, [])
            self.assertEqual(issues, {})
            self.assertTrue(loaded["CEN-02"]["pass"])

    def test_load_field_report_accepts_cen02_observed_alias_and_event_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.json"
            path.write_text(
                json.dumps(
                    {
                        "scenarios": {
                            "CEN-02": {
                                "result": "pass",
                                "evidence_ref": "artifact://cen02",
                                "transition_evidence": [
                                    {
                                        "transition_state": "SUSPECT",
                                        "observed": "true",
                                        "screenshot_ref": "artifact://suspect.png",
                                        "trace_ref": "artifact://suspect.jsonl",
                                        "status_endpoint_ref": "artifact://suspect.status.txt",
                                        "expected_vs_observed": "ok",
                                        "trigger_action": "zoom-in",
                                        "event_timestamp_utc": "2026-04-30T14:10:00Z",
                                    },
                                    {
                                        "transition_state": "FROZEN",
                                        "observed": 1,
                                        "screenshot_ref": "artifact://frozen.png",
                                        "trace_ref": "artifact://frozen.jsonl",
                                        "status_endpoint_ref": "artifact://frozen.status.txt",
                                        "expected_vs_observed": "ok",
                                        "freeze_duration_ms": "3200",
                                        "event_timestamp_utc": "2026-04-30T14:10:05Z",
                                    },
                                    {
                                        "transition_state": "RECALIBRATING",
                                        "observed": "sim",
                                        "screenshot_ref": "artifact://recal.png",
                                        "trace_ref": "artifact://recal.jsonl",
                                        "status_endpoint_ref": "artifact://recal.status.txt",
                                        "expected_vs_observed": "ok",
                                        "stable_return_ref": "artifact://stable-return.png",
                                        "observed_at_utc": "2026-04-30T14:10:09Z",
                                    },
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            loaded, issues, global_issues = validator._load_field_report(path)
            self.assertEqual(global_issues, [])
            self.assertEqual(issues, {})
            self.assertTrue(loaded["CEN-02"]["pass"])

    def test_load_field_report_reports_cen02_duplicated_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.json"
            path.write_text(
                json.dumps(
                    {
                        "scenarios": {
                            "CEN-02": {
                                "result": "pass",
                                "evidence_ref": "artifact://cen02",
                                "transition_evidence": [
                                    {"transition_state": "SUSPECT", "observed": True},
                                    {"transition_state": "SUSPECT", "observed": True},
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            _, issues, _ = validator._load_field_report(path)
            self.assertIn("CEN-02", issues)
            self.assertTrue(any("duplicated_transition" in item for item in issues["CEN-02"]))

    def test_scenario_result_cen04_requires_dpi_matrix_contract(self) -> None:
        row = validator._scenario_result(
            {"id": "CEN-04", "ovr_id": "OVR-STAB-QA-04", "title": "Multi-monitor DPI"},
            qa_manifest={"ovr_status": {"OVR-STAB-QA-04": {"state": "partial-done"}}},
            stress_manifest={},
            field_scenarios={"CEN-04": {"pass": True, "evidence_ref": "artifact://cen04"}},
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("CEN-04:missing_monitor_dpi_matrix|acao:", row["field_validation"]["details"])
        self.assertTrue(any(gap["gap_id"] == "GAP-CEN-04-FIELD" for gap in row["gaps"]))
        self.assertIn("issues", row["field_validation"])
        self.assertGreaterEqual(row["diagnostics"]["field_issue_count"], 1)

    def test_scenario_result_cen04_requires_drift_steps_contract(self) -> None:
        row = validator._scenario_result(
            {"id": "CEN-04", "ovr_id": "OVR-STAB-QA-04", "title": "Multi-monitor DPI"},
            qa_manifest={"ovr_status": {"OVR-STAB-QA-04": {"state": "partial-done"}}},
            stress_manifest={},
            field_scenarios={
                "CEN-04": {
                    "pass": True,
                    "evidence_ref": "artifact://cen04",
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
                            "drift_px": 1.0,
                            "evidence_ref": "artifact://m2",
                        },
                        {
                            "monitor_id": "monitor-3",
                            "dpi_percent": 150,
                            "transition": "move-to-monitor",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 1.0,
                            "evidence_ref": "artifact://m3",
                        },
                    ],
                    "drift_steps": [{"step_id": "open_window_on_baseline_monitor", "drift_px": 1.0}],
                }
            },
            field_report_issues={},
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("CEN-04:missing_drift_step_monitor_id:0|acao:", row["field_validation"]["details"])
        self.assertIn("CEN-04:missing_required_drift_step:move_window_to_next_monitor|acao:", row["field_validation"]["details"])

    def test_main_integration_with_realistic_field_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_path = root / "qa.manifest.json"
            stress_path = root / "stress.manifest.json"
            field_path = root / "field-report.json"
            out_dir = root / "out"

            qa_path.write_text(
                json.dumps(
                    {
                        "ovr_status": {
                            "OVR-STAB-QA-01": {"state": "partial-done"},
                            "OVR-STAB-QA-02": {"state": "partial-done"},
                            "OVR-STAB-QA-03": {"state": "partial-done"},
                            "OVR-STAB-QA-04": {"state": "partial-done"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            stress_path.write_text(json.dumps({"gate": {"ok": True}}), encoding="utf-8")
            field_path.write_text(
                json.dumps(
                    {
                        "scenarios": [
                            {
                                "scenario_id": "CEN-01",
                                "result": "pass",
                                "evidence_ref": "artifact://cen01",
                            },
                            {
                                "scenario_id": "CEN-02",
                                "result": "pass",
                                "evidence_refs": {"summary_manifest": "artifact://cen02-summary"},
                            },
                            {
                                "scenario_id": "CEN-03",
                                "result": "pass",
                                "evidence_ref": "artifact://cen03",
                                "incident_packages": [
                                    {
                                        "incident_id": "CEN-03-INC-READY-001",
                                        "expected_vs_observed_by_channel": {
                                            "hud": {
                                                "expected": "axis_status=FROZEN",
                                                "observed": "axis_status=FROZEN",
                                                "evidence_ref": "artifact://cen03-hud",
                                            },
                                            "status_endpoint": {
                                                "expected": "bad_frames increase then recover",
                                                "observed": "bad_frames=6 then 0",
                                                "evidence_ref": "artifact://cen03-status",
                                            },
                                            "trace_jsonl": {
                                                "expected": "recovery transition to STABLE logged",
                                                "observed": "recovery transition to STABLE logged",
                                                "evidence_ref": "artifact://cen03-trace",
                                            },
                                        },
                                        "observed_state_transitions": [
                                            "STABLE->FROZEN|RECALIBRATING",
                                            "FROZEN|RECALIBRATING->STABLE",
                                        ],
                                        "evidence_ref": [
                                            "artifact://cen03-a",
                                            "artifact://cen03-b",
                                            "artifact://cen03-c",
                                        ],
                                    }
                                ],
                            },
                            {
                                "scenario_id": "CEN-04",
                                "result": "pass",
                                "evidence_ref": "artifact://cen04",
                                "monitor_dpi_matrix": [
                                    {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open", "bounds_ok": True, "overlay_ok": True, "drift_px": 1.0, "evidence_ref": "artifact://cen04-m1"},
                                    {"monitor_id": "monitor-2", "dpi_percent": 125, "transition": "move-to-monitor", "bounds_ok": True, "overlay_ok": True, "drift_px": 1.1, "evidence_ref": "artifact://cen04-m2"},
                                    {"monitor_id": "monitor-3", "dpi_percent": 150, "transition": "move-to-monitor", "bounds_ok": True, "overlay_ok": True, "drift_px": 1.2, "evidence_ref": "artifact://cen04-m3"},
                                ],
                                "drift_steps": [
                                    {"step_id": "open_window_on_baseline_monitor", "monitor_id": "monitor-1", "dpi_percent": 100, "axis_status_before": "STABLE", "axis_status_after": "STABLE", "drift_px": 1.0, "evidence_ref": "artifact://s1"},
                                    {"step_id": "move_window_to_next_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "STABLE", "axis_status_after": "RECALIBRATING", "drift_px": 1.0, "evidence_ref": "artifact://s2"},
                                    {"step_id": "minimize_window_on_target_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "RECALIBRATING", "axis_status_after": "FROZEN", "drift_px": 1.0, "evidence_ref": "artifact://s3"},
                                    {"step_id": "restore_window_on_target_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "FROZEN", "axis_status_after": "RECALIBRATING", "drift_px": 1.0, "evidence_ref": "artifact://s4"},
                                    {"step_id": "move_window_back_to_baseline_monitor", "monitor_id": "monitor-3", "dpi_percent": 150, "axis_status_before": "RECALIBRATING", "axis_status_after": "STABLE", "drift_px": 1.0, "evidence_ref": "artifact://s5"},
                                ],
                            },
                            {
                                "scenario_id": "CEN-05",
                                "session_type": "manual-field",
                                "pass": True,
                                "result": "pass",
                                "evidence_ref": "artifact://cen05",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "verify_ovr_stab_g8_readiness.py",
                    "--qa-manifest",
                    str(qa_path),
                    "--stress-manifest",
                    str(stress_path),
                    "--field-report",
                    str(field_path),
                    "--out-dir",
                    str(out_dir),
                    "--strict",
                ]
                exit_code = validator.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(exit_code, 0)
            manifest_payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest_payload["g8_ready"])
            self.assertEqual(manifest_payload["contract_version"], "1.1")
            self.assertIn("report_contract", manifest_payload)
            self.assertIn("executive_summary", manifest_payload)
            self.assertEqual(manifest_payload["executive_summary"]["status"], "PASS")
            self.assertEqual(manifest_payload["executive_summary"]["top_blockers"], [])
            self.assertEqual(manifest_payload["field_report_validation"]["global_issues"], [])
            self.assertIn("CEN-02", manifest_payload["field_report_validation"]["scenario_issues"])

    def test_main_integration_diagnostics_with_field_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_path = root / "qa.manifest.json"
            stress_path = root / "stress.manifest.json"
            field_path = root / "field-report.json"
            out_dir = root / "out"

            qa_path.write_text(
                json.dumps({"ovr_status": {"OVR-STAB-QA-01": {"state": "partial-done"}, "OVR-STAB-QA-02": {"state": "partial-done"}}}),
                encoding="utf-8",
            )
            stress_path.write_text(json.dumps({"gate": {"ok": False, "failures": ["latency_p95_ms > 60"]}}), encoding="utf-8")
            field_path.write_text(
                json.dumps({"scenarios": {"CEN-02": {"result": "pass"}}}),
                encoding="utf-8",
            )

            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "verify_ovr_stab_g8_readiness.py",
                    "--qa-manifest",
                    str(qa_path),
                    "--stress-manifest",
                    str(stress_path),
                    "--field-report",
                    str(field_path),
                    "--out-dir",
                    str(out_dir),
                    "--strict",
                ]
                exit_code = validator.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(exit_code, 2)
            manifest_payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest_payload["g8_ready"])
            self.assertIn("executive_summary", manifest_payload)
            self.assertEqual(manifest_payload["executive_summary"]["status"], "FAIL")
            self.assertGreaterEqual(manifest_payload["executive_summary"]["blocker_count"], 1)
            self.assertGreaterEqual(len(manifest_payload["executive_summary"]["top_blockers"]), 1)
            self.assertIn("CEN-02", manifest_payload["field_report_validation"]["scenario_issues"])
            scenario_map = {row["scenario_id"]: row for row in manifest_payload["scenario_results"]}
            self.assertIn("missing_evidence_ref", scenario_map["CEN-02"]["field_validation"]["details"])
            self.assertIn("CEN-02:SUSPECT:missing_transition|acao:", scenario_map["CEN-02"]["field_validation"]["details"])
            self.assertIn("field-report invalido", scenario_map["CEN-02"]["gaps"][0]["reason"])
            self.assertIn("incident_evidence_index", scenario_map["CEN-03"]["field_validation"])

    def test_main_strict_with_local_incomplete_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_path = root / "qa.manifest.json"
            stress_path = root / "stress.manifest.json"
            out_dir = root / "out"
            fixture_path = Path(__file__).resolve().parent / "fixtures" / "field_report_real_integration.json"

            qa_path.write_text(
                json.dumps(
                    {
                        "ovr_status": {
                            "OVR-STAB-QA-01": {"state": "partial-done"},
                            "OVR-STAB-QA-02": {"state": "partial-done"},
                            "OVR-STAB-QA-03": {"state": "partial-done"},
                            "OVR-STAB-QA-04": {"state": "partial-done"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            stress_path.write_text(json.dumps({"gate": {"ok": True}, "overall_ok": True}), encoding="utf-8")

            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "verify_ovr_stab_g8_readiness.py",
                    "--qa-manifest",
                    str(qa_path),
                    "--stress-manifest",
                    str(stress_path),
                    "--field-report",
                    str(fixture_path),
                    "--out-dir",
                    str(out_dir),
                    "--strict",
                ]
                exit_code = validator.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(exit_code, 2)
            manifest_payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            scenario_map = {row["scenario_id"]: row for row in manifest_payload["scenario_results"]}
            self.assertEqual(scenario_map["CEN-05"]["status"], "PASS")
            self.assertEqual(scenario_map["CEN-03"]["status"], "FAIL")
            self.assertIn("|acao:", scenario_map["CEN-03"]["field_validation"]["details"])

    def test_main_strict_with_local_complete_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_path = root / "qa.manifest.json"
            stress_path = root / "stress.manifest.json"
            out_dir = root / "out"
            fixture_path = Path(__file__).resolve().parent / "fixtures" / "field_report_real_complete_integration.json"

            qa_path.write_text(
                json.dumps(
                    {
                        "ovr_status": {
                            "OVR-STAB-QA-01": {"state": "partial-done"},
                            "OVR-STAB-QA-02": {"state": "partial-done"},
                            "OVR-STAB-QA-03": {"state": "partial-done"},
                            "OVR-STAB-QA-04": {"state": "partial-done"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            stress_path.write_text(json.dumps({"gate": {"ok": True}, "overall_ok": True}), encoding="utf-8")

            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "verify_ovr_stab_g8_readiness.py",
                    "--qa-manifest",
                    str(qa_path),
                    "--stress-manifest",
                    str(stress_path),
                    "--field-report",
                    str(fixture_path),
                    "--out-dir",
                    str(out_dir),
                    "--strict",
                ]
                exit_code = validator.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(exit_code, 0)
            manifest_payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest_payload["g8_ready"])


if __name__ == "__main__":
    unittest.main()
