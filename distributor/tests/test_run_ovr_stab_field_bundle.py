from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_ovr_stab_field_bundle.py"
    spec = importlib.util.spec_from_file_location("run_ovr_stab_field_bundle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module()


class TestRunOvrStabFieldBundle(unittest.TestCase):
    def test_validate_cen02_transition_evidence_ok(self) -> None:
        payload = {
            "scenarios": {
                "CEN-02": {
                    "transition_evidence": [
                        {
                            "transition_state": "SUSPECT",
                            "observed": True,
                            "screenshot_ref": "artifact://cen02-suspect.png",
                            "trace_ref": "artifact://cen02-suspect.jsonl",
                            "status_endpoint_ref": "artifact://cen02-suspect-status.txt",
                            "expected_vs_observed": "status divergiu por 4s e voltou",
                            "trigger_action": "zoom-in",
                            "observed_at_utc": "2026-04-30T14:00:01Z",
                        },
                        {
                            "transition_state": "FROZEN",
                            "observed": True,
                            "screenshot_ref": "artifact://cen02-frozen.png",
                            "trace_ref": "artifact://cen02-frozen.jsonl",
                            "status_endpoint_ref": "artifact://cen02-frozen-status.txt",
                            "expected_vs_observed": "freeze confirmado sob zoom brusco",
                            "freeze_duration_ms": "2800",
                            "observed_at_utc": "2026-04-30T14:00:05Z",
                        },
                        {
                            "transition_state": "RECALIBRATING",
                            "observed": True,
                            "screenshot_ref": "artifact://cen02-recal.png",
                            "trace_ref": "artifact://cen02-recal.jsonl",
                            "status_endpoint_ref": "artifact://cen02-recal-status.txt",
                            "expected_vs_observed": "recalibrou e estabilizou",
                            "stable_return_ref": "artifact://cen02-stable.png",
                            "observed_at_utc": "2026-04-30T14:00:09Z",
                        },
                    ]
                }
            }
        }
        report = runner._validate_cen02_transition_evidence(payload)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_transitions"], 3)
        self.assertEqual(report["errors"], [])

    def test_validate_cen02_transition_evidence_reports_missing_fields(self) -> None:
        payload = {
            "scenarios": {
                "CEN-02": {
                    "transition_evidence": [
                        {"transition_state": "SUSPECT", "screenshot_ref": "artifact://cen02-suspect.png"},
                        {
                            "transition_state": "RECALIBRATING",
                            "screenshot_ref": "artifact://cen02-recal.png",
                            "trace_ref": "artifact://cen02-recal.jsonl",
                            "status_endpoint_ref": "artifact://cen02-recal-status.txt",
                            "expected_vs_observed": "ok",
                        },
                    ]
                }
            }
        }
        report = runner._validate_cen02_transition_evidence(payload)
        self.assertFalse(report["ok"])
        self.assertIn(
            "CEN-02:FROZEN:missing_transition|acao:registrar evento FROZEN com evidencias minimas", report["errors"]
        )
        self.assertIn(
            "CEN-02:SUSPECT:missing_trace_ref|acao:preencher trace_ref para a transicao SUSPECT", report["errors"]
        )
        self.assertIn(
            "CEN-02:SUSPECT:observed_not_true|acao:marcar observed=true apos confirmacao em campo", report["errors"]
        )

    def test_validate_cen02_transition_evidence_accepts_observed_string_and_event_timestamp(self) -> None:
        payload = {
            "scenarios": {
                "CEN-02": {
                    "transition_evidence": [
                        {
                            "transition_state": "SUSPECT",
                            "observed": "true",
                            "screenshot_ref": "artifact://cen02-suspect.png",
                            "trace_ref": "artifact://cen02-suspect.jsonl",
                            "status_endpoint_ref": "artifact://cen02-suspect-status.txt",
                            "expected_vs_observed": "ok",
                            "trigger_action": "zoom-in",
                            "event_timestamp_utc": "2026-04-30T14:00:01Z",
                        },
                        {
                            "transition_state": "FROZEN",
                            "observed": 1,
                            "screenshot_ref": "artifact://cen02-frozen.png",
                            "trace_ref": "artifact://cen02-frozen.jsonl",
                            "status_endpoint_ref": "artifact://cen02-frozen-status.txt",
                            "expected_vs_observed": "ok",
                            "freeze_duration_ms": "2500",
                            "event_timestamp_utc": "2026-04-30T14:00:05Z",
                        },
                        {
                            "transition_state": "RECALIBRATING",
                            "observed": "sim",
                            "screenshot_ref": "artifact://cen02-recal.png",
                            "trace_ref": "artifact://cen02-recal.jsonl",
                            "status_endpoint_ref": "artifact://cen02-recal-status.txt",
                            "expected_vs_observed": "ok",
                            "stable_return_ref": "artifact://cen02-stable.png",
                            "observed_at_utc": "2026-04-30T14:00:09Z",
                        },
                    ]
                }
            }
        }
        report = runner._validate_cen02_transition_evidence(payload)
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_validate_cen02_transition_evidence_rejects_duplicated_transition(self) -> None:
        payload = {
            "scenarios": {
                "CEN-02": {
                    "transition_evidence": [
                        {"transition_state": "SUSPECT"},
                        {"transition_state": "SUSPECT"},
                    ]
                }
            }
        }
        report = runner._validate_cen02_transition_evidence(payload)
        self.assertFalse(report["ok"])
        self.assertIn(
            "CEN-02:SUSPECT:duplicated_transition|acao:manter apenas um registro por transition_state",
            report["errors"],
        )

    def test_validate_cen03_incident_packages_ok(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-001",
                            "expected_vs_observed_by_channel": {
                                "hud": {
                                    "expected": "axis_status=FROZEN",
                                    "observed": "axis_status=FROZEN",
                                    "evidence_ref": "artifact://hud.png",
                                },
                                "status_endpoint": {
                                    "expected": "bad_frames>0",
                                    "observed": "bad_frames=3",
                                    "evidence_ref": "artifact://status.json",
                                },
                                "trace_jsonl": {
                                    "expected": "transition FROZEN para STABLE logged",
                                    "observed": "transition FROZEN para STABLE logged",
                                    "evidence_ref": "artifact://trace.jsonl",
                                },
                            },
                            "observed_state_transitions": [
                                "STABLE->FROZEN|RECALIBRATING",
                                "FROZEN|RECALIBRATING->STABLE",
                            ],
                            "evidence_ref": ["artifact://a.png", "artifact://a.jsonl", "artifact://a.log"],
                        }
                    ]
                }
            }
        }
        report = runner.validate_cen03_incident_packages(payload)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_incidents"], 1)
        self.assertEqual(report["errors"], [])

    def test_validate_cen03_incident_packages_reports_missing_channels(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-002",
                            "expected_vs_observed_by_channel": {
                                "hud": {
                                    "expected": "axis_status=FROZEN",
                                    "observed": "axis_status=FROZEN",
                                    "evidence_ref": "artifact://hud.png",
                                }
                            },
                            "observed_state_transitions": [
                                "STABLE->FROZEN|RECALIBRATING",
                                "FROZEN|RECALIBRATING->STABLE",
                            ],
                            "evidence_ref": ["artifact://a.png", "artifact://a.jsonl", "artifact://a.log"],
                        }
                    ]
                }
            }
        }
        report = runner.validate_cen03_incident_packages(payload)
        self.assertFalse(report["ok"])
        self.assertIn("CEN-03-INC-002:missing_channel:status_endpoint", report["errors"])
        self.assertIn("CEN-03-INC-002:missing_channel:trace_jsonl", report["errors"])

    def test_validate_cen03_incident_packages_reports_missing_incident_id(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {
                            "expected_vs_observed_by_channel": {
                                "hud": {"expected": "exp", "observed": "obs", "evidence_ref": "artifact://hud.png"},
                                "status_endpoint": {
                                    "expected": "exp",
                                    "observed": "obs",
                                    "evidence_ref": "artifact://status.json",
                                },
                                "trace_jsonl": {
                                    "expected": "exp",
                                    "observed": "obs",
                                    "evidence_ref": "artifact://trace.jsonl",
                                },
                            }
                            ,
                            "observed_state_transitions": [
                                "STABLE->FROZEN|RECALIBRATING",
                                "FROZEN|RECALIBRATING->STABLE",
                            ],
                            "evidence_ref": ["artifact://a.png", "artifact://a.jsonl", "artifact://a.log"],
                        }
                    ]
                }
            }
        }
        report = runner.validate_cen03_incident_packages(payload)
        self.assertFalse(report["ok"])
        self.assertIn("incident[0]:missing_incident_id", report["errors"])

    def test_validate_cen03_incident_packages_requires_channel_evidence_and_transitions(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-003",
                            "expected_vs_observed_by_channel": {
                                "hud": {"expected": "exp", "observed": "obs"},
                                "status_endpoint": {"expected": "exp", "observed": "obs"},
                                "trace_jsonl": {"expected": "exp", "observed": "obs"},
                            },
                            "observed_state_transitions": ["STABLE->FROZEN|RECALIBRATING"],
                            "evidence_ref": ["artifact://only-one"],
                        }
                    ]
                }
            }
        }
        report = runner.validate_cen03_incident_packages(payload)
        self.assertFalse(report["ok"])
        self.assertIn("CEN-03-INC-003:missing_channel_evidence_ref:hud", report["errors"])
        self.assertIn("CEN-03-INC-003:missing_channel_evidence_ref:status_endpoint", report["errors"])
        self.assertIn("CEN-03-INC-003:missing_channel_evidence_ref:trace_jsonl", report["errors"])
        self.assertIn("CEN-03-INC-003:missing_transition:FROZEN|RECALIBRATING->STABLE", report["errors"])
        self.assertIn("CEN-03-INC-003:insufficient_incident_evidence_refs", report["errors"])

    def test_validate_cen03_incident_packages_reports_semantic_mismatch(self) -> None:
        payload = {
            "scenarios": {
                "CEN-03": {
                    "incident_packages": [
                        {
                            "incident_id": "CEN-03-INC-004",
                            "expected_vs_observed_by_channel": {
                                "hud": {
                                    "expected": "axis_status=FROZEN",
                                    "observed": "ui without state info",
                                    "evidence_ref": "artifact://hud.png",
                                },
                                "status_endpoint": {
                                    "expected": "bad_frames increased during degradation",
                                    "observed": "endpoint answered without axis state",
                                    "evidence_ref": "artifact://status.json",
                                },
                                "trace_jsonl": {
                                    "expected": "recovery to STABLE after degradation removal",
                                    "observed": "trace file updated",
                                    "evidence_ref": "artifact://trace.jsonl",
                                },
                            },
                            "observed_state_transitions": [
                                "STABLE->FROZEN|RECALIBRATING",
                                "FROZEN|RECALIBRATING->STABLE",
                            ],
                            "evidence_ref": ["artifact://a.png", "artifact://a.jsonl", "artifact://a.log"],
                        }
                    ]
                }
            }
        }
        report = runner.validate_cen03_incident_packages(payload)
        self.assertFalse(report["ok"])
        self.assertIn("CEN-03-INC-004:semantic_mismatch:hud", report["errors"])
        self.assertIn("CEN-03-INC-004:semantic_mismatch:status_endpoint", report["errors"])
        self.assertIn("CEN-03-INC-004:semantic_mismatch:trace_jsonl", report["errors"])
        self.assertIn("CEN-03-INC-004:missing_protection_signal_in_observed", report["errors"])
        self.assertIn("CEN-03-INC-004:missing_recovery_signal_in_observed", report["errors"])

    def test_validate_cen04_field_matrix_ok(self) -> None:
        payload = {
            "scenarios": {
                "CEN-04": {
                    "monitor_dpi_matrix": [
                        {
                            "monitor_id": "monitor-1",
                            "dpi_percent": 100,
                            "transition": "baseline-open",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 1.2,
                            "evidence_ref": "artifact://cen04/m1.png",
                        },
                        {
                            "monitor_id": "monitor-2",
                            "dpi_percent": 125,
                            "transition": "move-to-monitor",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 1.6,
                            "evidence_ref": "artifact://cen04/m2.png",
                        },
                        {
                            "monitor_id": "monitor-3",
                            "dpi_percent": 150,
                            "transition": "move-to-monitor",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 2.1,
                            "evidence_ref": "artifact://cen04/m3.png",
                        },
                    ],
                    "drift_steps": [
                        {"step_id": "open_window_on_baseline_monitor", "monitor_id": "monitor-1", "dpi_percent": 100, "axis_status_before": "STABLE", "axis_status_after": "STABLE", "drift_px": 0.9, "evidence_ref": "artifact://s1"},
                        {"step_id": "move_window_to_next_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "STABLE", "axis_status_after": "RECALIBRATING", "drift_px": 1.4, "evidence_ref": "artifact://s2"},
                        {"step_id": "minimize_window_on_target_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "RECALIBRATING", "axis_status_after": "FROZEN", "drift_px": 0.8, "evidence_ref": "artifact://s3"},
                        {"step_id": "restore_window_on_target_monitor", "monitor_id": "monitor-2", "dpi_percent": 125, "axis_status_before": "FROZEN", "axis_status_after": "RECALIBRATING", "drift_px": 1.1, "evidence_ref": "artifact://s4"},
                        {"step_id": "move_window_back_to_baseline_monitor", "monitor_id": "monitor-3", "dpi_percent": 150, "axis_status_before": "RECALIBRATING", "axis_status_after": "STABLE", "drift_px": 1.7, "evidence_ref": "artifact://s5"},
                    ],
                }
            }
        }
        report = runner._validate_cen04_field_matrix(payload)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_rows"], 3)
        self.assertEqual(report["checked_steps"], 5)

    def test_validate_cen04_field_matrix_reports_missing_coverage(self) -> None:
        payload = {
            "scenarios": {
                "CEN-04": {
                    "monitor_dpi_matrix": [
                        {
                            "monitor_id": "monitor-1",
                            "dpi_percent": 100,
                            "transition": "baseline-open",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 1.2,
                            "evidence_ref": "artifact://cen04/m1.png",
                        }
                    ],
                    "drift_steps": [],
                }
            }
        }
        report = runner._validate_cen04_field_matrix(payload)
        self.assertFalse(report["ok"])
        self.assertIn("CEN-04.monitor_dpi_matrix_invalid_dpi_coverage_required_100_125_150", report["errors"])
        self.assertIn("CEN-04.drift_steps_missing_or_empty", report["errors"])

    def test_validate_cen04_field_matrix_reports_transition_and_step_contract_errors(self) -> None:
        payload = {
            "scenarios": {
                "CEN-04": {
                    "monitor_dpi_matrix": [
                        {
                            "monitor_id": "monitor-1",
                            "dpi_percent": 100,
                            "transition": "invalid-transition",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 1.0,
                            "evidence_ref": "artifact://cen04/m1",
                        },
                        {
                            "monitor_id": "monitor-2",
                            "dpi_percent": 100,
                            "transition": "move-to-monitor",
                            "bounds_ok": True,
                            "overlay_ok": True,
                            "drift_px": 1.0,
                            "evidence_ref": "artifact://cen04/m2",
                        },
                    ],
                    "drift_steps": [
                        {
                            "step_id": "open_window_on_baseline_monitor",
                            "drift_px": 0.8,
                            "evidence_ref": "artifact://s1",
                        },
                        {
                            "step_id": "open_window_on_baseline_monitor",
                            "monitor_id": "monitor-1",
                            "dpi_percent": 100,
                            "axis_status_before": "STABLE",
                            "axis_status_after": "STABLE",
                            "drift_px": 0.9,
                            "evidence_ref": "artifact://s2",
                        },
                    ],
                }
            }
        }
        report = runner._validate_cen04_field_matrix(payload)
        self.assertFalse(report["ok"])
        self.assertIn("CEN-04.monitor_dpi_matrix[0]:invalid_transition:invalid-transition", report["errors"])
        self.assertIn("CEN-04.monitor_dpi_matrix[1]:duplicated_dpi_percent:100", report["errors"])
        self.assertIn("CEN-04.drift_steps[0]:missing_monitor_id", report["errors"])
        self.assertIn("CEN-04.drift_steps[0]:dpi_percent_not_integer", report["errors"])
        self.assertIn("CEN-04.drift_steps[0]:missing_axis_status_before", report["errors"])
        self.assertIn("CEN-04.drift_steps[1]:duplicated_step_id:open_window_on_baseline_monitor", report["errors"])

    def test_validate_required_files_detects_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "summary.md").write_text("ok\n", encoding="utf-8")
            report = runner._validate_required_files(base, ("summary.md", "summary.manifest.json"))
            self.assertFalse(report["ok"])
            self.assertEqual(report["checked_count"], 2)
            self.assertEqual(len(report["missing"]), 1)

    def test_build_summary_mentions_manual_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.md"
            payload = {
                "strict_ok": False,
                "qa": {"ok": True, "artifacts_ok": True},
                "stress": {"ok": False, "artifacts_ok": False},
                "readiness": {"ok": False},
                "bundle_artifacts_ok": True,
                "bundle_runner_logs_ok": True,
                "cen03_incident_packages_check": {"ok": False, "checked_incidents": 2},
                "manual_gaps": ["CEN-04: campo pendente/nao aprovado"],
            }
            runner._build_summary_md(out, payload)
            content = out.read_text(encoding="utf-8")
            self.assertIn("strict_ok: `0`", content)
            self.assertIn("cen03_incident_packages_ok: `0`", content)
            self.assertIn("CEN-04: campo pendente/nao aprovado", content)

    def test_build_commands_includes_core_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "commands.ready.md"
            runner._build_commands_md(
                out,
                {
                    "qa_manifest": "qa/summary.manifest.json",
                    "stress_manifest": "stress/summary.manifest.json",
                    "readiness_manifest": "ready/summary.manifest.json",
                    "cen04_drift_worksheet": "bundle/cen04_drift_worksheet.md",
                },
            )
            content = out.read_text(encoding="utf-8")
            self.assertIn("run_ovr_stab_qa_evidence.py", content)
            self.assertIn("run_overlay_ws_stress_regression.py", content)
            self.assertIn("verify_ovr_stab_g8_readiness.py", content)
            self.assertIn("check_cen04_monitor_dpi_matrix.py", content)
            self.assertIn("verify_cen05_preflight.py", content)
            self.assertIn("--require-ovr OVR-STAB-QA-03", content)
            self.assertIn("cen02.operator.template.md", content)
            self.assertIn("cen02.minimum_checks.json", content)
            self.assertIn("cen04_drift_worksheet", content)

    def test_load_json_invalid_returns_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{invalid", encoding="utf-8")
            self.assertEqual(runner._load_json(bad), {})

    def test_build_checklist_has_all_cen_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "field_execution.checklist.md"
            runner._build_checklist_md(out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("## CEN-02 Zoom/Escala", content)
            self.assertIn("## CEN-03 OCR degradado", content)
            self.assertIn("baseline_check -> inject_degradation -> confirm_protection -> recover_signal", content)
            self.assertIn("## CEN-04 Multi-monitor 100/125/150", content)
            self.assertIn("cen04_drift_worksheet.md", content)
            self.assertIn("### CEN-04 Execucao curta (bancada multi-monitor)", content)
            self.assertIn("| monitor-1 | 100 | baseline-open", content)
            self.assertIn("#### Criterios de aceite instantaneos (CEN-04)", content)
            self.assertIn("## CEN-05 Carga real", content)

    def test_build_cen04_worksheet_has_drift_table_and_naming(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cen04_drift_worksheet.md"
            runner._build_cen04_drift_worksheet_md(out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("## Artifacts naming padrao", content)
            self.assertIn("evidence_ref (recomendado)", content)
            self.assertIn("## Drift por passo (preencher durante execucao fisica)", content)
            self.assertIn("| step_seq | step_id |", content)
            self.assertIn("drift_px <= 3.0", content)

    def test_manifest_roundtrip_ascii_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.manifest.json"
            payload = {"runner": "run_ovr_stab_field_bundle.py", "strict_ok": False}
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            parsed = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(parsed["runner"], "run_ovr_stab_field_bundle.py")

    def test_build_cen02_operator_template_has_placeholders_and_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cen02.operator.template.md"
            runner._build_cen02_operator_template_md(out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("# CEN-02 Operator Template (field-ready)", content)
            self.assertIn("session_id: <preencher>", content)
            self.assertIn("| SUSPECT | [ ] |", content)
            self.assertIn("| FROZEN | [ ] |", content)
            self.assertIn("| RECALIBRATING | [ ] |", content)
            self.assertIn("status_endpoint_ref", content)
            self.assertIn("expected_vs_observed", content)
            self.assertIn("drift_px_max apos retorno STABLE <= 3.0", content)

    def test_build_cen02_minimum_checks_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cen02.minimum_checks.json"
            runner._build_cen02_minimum_checks_json(out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["scenario_id"], "CEN-02")
            self.assertEqual(payload["required_transitions"], ["SUSPECT", "FROZEN", "RECALIBRATING"])
            self.assertEqual(payload["minimum_gates"]["drift_px_max_after_stable"]["value"], 3.0)
            self.assertIn("status_endpoint_ref", payload["required_fields"]["transitions"])
            self.assertIn("expected_vs_observed", payload["required_fields"]["transitions"])
            self.assertEqual(
                payload["required_transition_evidence_fields"],
                ["screenshot_ref", "trace_ref", "status_endpoint_ref", "expected_vs_observed"],
            )
            self.assertIn("evidence_ref", payload["required_fields"]["steps"])
            self.assertIn("evidence_ref", payload["required_fields"]["transitions"])

    def test_build_cen02_field_report_fixture_json_has_all_required_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cen02.field_report.fixture.json"
            payload = runner._build_cen02_field_report_fixture_json(out)
            self.assertEqual(payload["scenarios"]["CEN-02"]["scenario_id"], "CEN-02")
            transitions = payload["scenarios"]["CEN-02"]["transition_evidence"]
            observed_states = {str(item.get("transition_state", "")).upper() for item in transitions}
            self.assertEqual(observed_states, {"SUSPECT", "FROZEN", "RECALIBRATING"})
            report = runner._validate_cen02_fixture_integrity(payload)
            self.assertTrue(report["ok"])
            self.assertEqual(report["checked_transitions"], 3)

    def test_validate_cen02_fixture_integrity_detects_missing_step_and_bad_drift(self) -> None:
        payload = {
            "scenarios": {
                "CEN-02": {
                    "scenario_id": "CEN-02",
                    "steps_executed": [
                        {
                            "step_id": "capturar_baseline_estavel_5s",
                            "executed": True,
                            "timestamp_utc": "2026-04-30T13:42:03Z",
                            "action": "captura baseline",
                            "axis_status_before": "STABLE",
                            "axis_status_after": "STABLE",
                            "stable_reached": True,
                            "evidence_ref": "artifact://cen02/baseline",
                        }
                    ],
                    "transition_evidence": [
                        {
                            "transition_state": "SUSPECT",
                            "observed": True,
                            "screenshot_ref": "artifact://cen02-suspect.png",
                            "trace_ref": "artifact://cen02-suspect.jsonl",
                            "status_endpoint_ref": "artifact://cen02-suspect-status.txt",
                            "expected_vs_observed": "ok",
                            "trigger_action": "zoom-in",
                            "observed_at_utc": "2026-04-30T14:00:01Z",
                        }
                    ],
                    "stable_return_observed": False,
                    "drift_px_max_after_stable": 4.2,
                    "result": "unknown",
                }
            }
        }
        report = runner._validate_cen02_fixture_integrity(payload)
        self.assertFalse(report["ok"])
        self.assertIn("fixture.CEN-02.missing_step:aplicar_zoom_in_progressivo", report["errors"])
        self.assertIn("fixture.CEN-02.stable_return_observed_not_true", report["errors"])
        self.assertIn("fixture.CEN-02.drift_px_max_after_stable_gt_3:4.2", report["errors"])
        self.assertIn("fixture.CEN-02.result_invalid", report["errors"])

    def test_validate_runner_logs_accepts_empty_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "step_03_readiness.stdout.log").write_text("ok\n", encoding="utf-8")
            (base / "step_03_readiness.stderr.log").write_text("", encoding="utf-8")
            report = runner._validate_runner_logs(base, ("step_03_readiness",))
            self.assertTrue(report["ok"])
            self.assertEqual(report["checked_count"], 2)

    def test_validate_bundle_contract_detects_missing_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "commands.ready.md").write_text("# commands\n", encoding="utf-8")
            (base / "field_execution.checklist.md").write_text("# checklist\n", encoding="utf-8")
            (base / "cen04_drift_worksheet.md").write_text("# worksheet\n", encoding="utf-8")
            report = runner._validate_bundle_contract(base)
            self.assertFalse(report["ok"])
            self.assertTrue(any(str(item).startswith("commands_missing_token:") for item in report["errors"]))
            self.assertTrue(any(str(item).startswith("checklist_missing_token:") for item in report["errors"]))
            self.assertTrue(any(str(item).startswith("worksheet_missing_token:") for item in report["errors"]))

    def test_main_skip_stress_removes_stress_from_strict_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_dir = root / "ovr-stab-qa-evidence-qa"
            readiness_dir = root / "ovr-stab-g8-readiness-ready"
            field_report = root / "field-report.json"
            out_dir = root / "bundle-out"
            preopen_dir = out_dir / "preopen"
            qa_dir.mkdir(parents=True, exist_ok=True)
            readiness_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            preopen_dir.mkdir(parents=True, exist_ok=True)

            for rel in ("summary.csv", "summary.md", "summary.manifest.json", "target_protocols.manifest.json", "target_protocols.checklist.md"):
                (qa_dir / rel).write_text("ok\n", encoding="utf-8")
            (qa_dir / "summary.manifest.json").write_text(json.dumps({"strict_ok": True}), encoding="utf-8")
            (readiness_dir / "summary.manifest.json").write_text(
                json.dumps({"g8_ready": True, "scenario_results": []}), encoding="utf-8"
            )
            (preopen_dir / "summary.manifest.json").write_text(
                json.dumps({"preflight_ok": True, "operational_messages": ["PREOPEN-GO"]}), encoding="utf-8"
            )
            (preopen_dir / "summary.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")
            field_report.write_text(
                json.dumps(
                    {
                        "scenarios": {
                            "CEN-02": {
                                "transition_evidence": [
                                    {
                                        "transition_state": "SUSPECT",
                                        "observed": True,
                                        "screenshot_ref": "artifact://cen02-suspect.png",
                                        "trace_ref": "artifact://cen02-suspect.jsonl",
                                        "status_endpoint_ref": "artifact://cen02-suspect-status.txt",
                                        "expected_vs_observed": "ok",
                                        "trigger_action": "zoom-in",
                                        "observed_at_utc": "2026-04-30T14:00:01Z",
                                    },
                                    {
                                        "transition_state": "FROZEN",
                                        "observed": True,
                                        "screenshot_ref": "artifact://cen02-frozen.png",
                                        "trace_ref": "artifact://cen02-frozen.jsonl",
                                        "status_endpoint_ref": "artifact://cen02-frozen-status.txt",
                                        "expected_vs_observed": "ok",
                                        "freeze_duration_ms": "2600",
                                        "observed_at_utc": "2026-04-30T14:00:05Z",
                                    },
                                    {
                                        "transition_state": "RECALIBRATING",
                                        "observed": True,
                                        "screenshot_ref": "artifact://cen02-recal.png",
                                        "trace_ref": "artifact://cen02-recal.jsonl",
                                        "status_endpoint_ref": "artifact://cen02-recal-status.txt",
                                        "expected_vs_observed": "ok",
                                        "stable_return_ref": "artifact://cen02-stable.png",
                                        "observed_at_utc": "2026-04-30T14:00:09Z",
                                    },
                                ]
                            },
                            "CEN-03": {
                                "incident_packages": [
                                    {
                                        "incident_id": "CEN-03-INC-001",
                                        "expected_vs_observed_by_channel": {
                                            "hud": {
                                                "expected": "axis_status=FROZEN",
                                                "observed": "axis_status=FROZEN",
                                                "evidence_ref": "artifact://hud.png",
                                            },
                                            "status_endpoint": {
                                                "expected": "bad_frames increased during degradation",
                                                "observed": "bad_frames=4",
                                                "evidence_ref": "artifact://status.json",
                                            },
                                            "trace_jsonl": {
                                                "expected": "recovery transition to STABLE after degradation removal",
                                                "observed": "recovery transition to STABLE logged",
                                                "evidence_ref": "artifact://trace.jsonl",
                                            },
                                        },
                                        "observed_state_transitions": [
                                            "STABLE->FROZEN|RECALIBRATING",
                                            "FROZEN|RECALIBRATING->STABLE",
                                        ],
                                        "evidence_ref": [
                                            "artifact://a.png",
                                            "artifact://a.jsonl",
                                            "artifact://a.log",
                                        ],
                                    }
                                ]
                            },
                            "CEN-04": {
                                "monitor_dpi_matrix": [
                                    {
                                        "monitor_id": "monitor-1",
                                        "dpi_percent": 100,
                                        "transition": "baseline-open",
                                        "bounds_ok": True,
                                        "overlay_ok": True,
                                        "drift_px": 1.0,
                                        "evidence_ref": "artifact://cen04/m1.png",
                                    },
                                    {
                                        "monitor_id": "monitor-2",
                                        "dpi_percent": 125,
                                        "transition": "move-to-monitor",
                                        "bounds_ok": True,
                                        "overlay_ok": True,
                                        "drift_px": 1.0,
                                        "evidence_ref": "artifact://cen04/m2.png",
                                    },
                                    {
                                        "monitor_id": "monitor-3",
                                        "dpi_percent": 150,
                                        "transition": "move-to-monitor",
                                        "bounds_ok": True,
                                        "overlay_ok": True,
                                        "drift_px": 1.0,
                                        "evidence_ref": "artifact://cen04/m3.png",
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
                            ,
                            "CEN-05": {
                                "result": "pass",
                                "session_type": "manual-field",
                                "evidence_ref": "artifact://cen05/stress",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            def fake_latest(prefix: str) -> Path | None:
                if prefix == "overlay-ws-stress-regression":
                    return None
                if prefix == "ovr-stab-qa-evidence":
                    return qa_dir
                if prefix == "ovr-stab-g8-readiness":
                    return readiness_dir
                return None

            def fake_run(cmd: list[str], run_out_dir: Path, step_id: str) -> dict[str, object]:
                (run_out_dir / f"{step_id}.stdout.log").write_text("ok\n", encoding="utf-8")
                (run_out_dir / f"{step_id}.stderr.log").write_text("", encoding="utf-8")
                (run_out_dir / "preopen.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")
                preopen_dir = run_out_dir / "preopen"
                preopen_dir.mkdir(parents=True, exist_ok=True)
                (preopen_dir / "summary.manifest.json").write_text(
                    json.dumps(
                        {
                            "preflight_ok": True,
                            "preopen_status_code": "PREOPEN_GO",
                            "checks": [
                                {
                                    "check_id": "artifacts",
                                    "status": "PASS",
                                    "preopen_status_code": "OK",
                                    "details": "ok",
                                    "next_step": "nenhum",
                                }
                            ],
                            "next_actions": [
                                {
                                    "priority": 1,
                                    "check_id": "go-live",
                                    "status_code": "PREOPEN_GO",
                                    "action": "iniciar",
                                    "command": "python scripts/run_ovr_stab_field_qa.py",
                                    "exit_criteria": "ok",
                                }
                            ],
                            "operational_messages": ["PREOPEN-GO"],
                        }
                    ),
                    encoding="utf-8",
                )
                if step_id == "step_04_cen04_matrix_audit":
                    audit_dir = run_out_dir / "cen04-matrix-audit"
                    audit_dir.mkdir(parents=True, exist_ok=True)
                    (audit_dir / "summary.manifest.json").write_text(
                        json.dumps({"ok": True, "issues": []}),
                        encoding="utf-8",
                    )
                return {"id": step_id, "ok": True, "exit_code": 0}

            with (
                mock.patch.object(runner, "_latest_dir", side_effect=fake_latest),
                mock.patch.object(runner, "_run", side_effect=fake_run),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_ovr_stab_field_bundle.py",
                        "--skip-stress",
                        "--out-dir",
                        str(out_dir),
                        "--field-report",
                        str(field_report),
                    ],
                ),
            ):
                code = runner.main()

            self.assertEqual(code, 0)
            payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["strict_ok"])
            self.assertEqual(payload["contract_version"], "1.1")
            self.assertTrue(payload["preopen_contract_ok"])
            self.assertFalse(payload["stress"]["required"])
            self.assertTrue(payload["qa"]["required"])
            self.assertTrue(payload["preopen"]["ok"])
            self.assertIn("CEN-03-INC-001", payload["cen03_incident_evidence_index"]["index"])
            self.assertEqual(
                payload["cen03_incident_evidence_index"]["index"]["CEN-03-INC-001"]["channels_with_evidence"],
                ["hud", "status_endpoint", "trace_jsonl"],
            )

    def test_main_strict_fails_when_cen03_channel_contract_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_dir = root / "ovr-stab-qa-evidence-qa"
            readiness_dir = root / "ovr-stab-g8-readiness-ready"
            field_report = root / "field-report.json"
            out_dir = root / "bundle-out"
            qa_dir.mkdir(parents=True, exist_ok=True)
            readiness_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            for rel in ("summary.csv", "summary.md", "summary.manifest.json", "target_protocols.manifest.json", "target_protocols.checklist.md"):
                (qa_dir / rel).write_text("ok\n", encoding="utf-8")
            (qa_dir / "summary.manifest.json").write_text(json.dumps({"strict_ok": True}), encoding="utf-8")
            (readiness_dir / "summary.manifest.json").write_text(
                json.dumps({"g8_ready": True, "scenario_results": []}), encoding="utf-8"
            )
            field_report.write_text(
                json.dumps(
                    {
                        "scenarios": {
                            "CEN-03": {
                                "incident_packages": [
                                    {
                                        "incident_id": "CEN-03-INC-STRICT-001",
                                        "expected_vs_observed_by_channel": {
                                            "hud": {"expected": "ok", "observed": "ok"},
                                            "status_endpoint": {"expected": "ok", "observed": "ok"},
                                            "trace_jsonl": {"expected": "ok", "observed": "ok"},
                                        },
                                        "observed_state_transitions": ["STABLE->FROZEN|RECALIBRATING"],
                                        "evidence_ref": ["artifact://single-ref"],
                                    }
                                ]
                            },
                            "CEN-05": {
                                "result": "pass",
                                "session_type": "manual-field",
                                "evidence_ref": "artifact://cen05/stress",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            def fake_latest(prefix: str) -> Path | None:
                if prefix == "overlay-ws-stress-regression":
                    return None
                if prefix == "ovr-stab-qa-evidence":
                    return qa_dir
                if prefix == "ovr-stab-g8-readiness":
                    return readiness_dir
                return None

            def fake_run(cmd: list[str], run_out_dir: Path, step_id: str) -> dict[str, object]:
                (run_out_dir / f"{step_id}.stdout.log").write_text("ok\n", encoding="utf-8")
                (run_out_dir / f"{step_id}.stderr.log").write_text("", encoding="utf-8")
                (run_out_dir / "preopen.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")
                preopen_dir = run_out_dir / "preopen"
                preopen_dir.mkdir(parents=True, exist_ok=True)
                (preopen_dir / "summary.manifest.json").write_text(
                    json.dumps(
                        {
                            "preflight_ok": True,
                            "preopen_status_code": "PREOPEN_GO",
                            "checks": [
                                {
                                    "check_id": "artifacts",
                                    "status": "PASS",
                                    "preopen_status_code": "OK",
                                    "details": "ok",
                                    "next_step": "nenhum",
                                }
                            ],
                            "next_actions": [
                                {
                                    "priority": 1,
                                    "check_id": "go-live",
                                    "status_code": "PREOPEN_GO",
                                    "action": "iniciar",
                                    "command": "python scripts/run_ovr_stab_field_qa.py",
                                    "exit_criteria": "ok",
                                }
                            ],
                            "operational_messages": ["PREOPEN-GO"],
                        }
                    ),
                    encoding="utf-8",
                )
                if step_id == "step_04_cen04_matrix_audit":
                    audit_dir = run_out_dir / "cen04-matrix-audit"
                    audit_dir.mkdir(parents=True, exist_ok=True)
                    (audit_dir / "summary.manifest.json").write_text(
                        json.dumps({"ok": True, "issues": []}),
                        encoding="utf-8",
                    )
                return {"id": step_id, "ok": True, "exit_code": 0}

            with (
                mock.patch.object(runner, "_latest_dir", side_effect=fake_latest),
                mock.patch.object(runner, "_run", side_effect=fake_run),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_ovr_stab_field_bundle.py",
                        "--skip-stress",
                        "--strict",
                        "--out-dir",
                        str(out_dir),
                        "--field-report",
                        str(field_report),
                    ],
                ),
            ):
                code = runner.main()

            self.assertEqual(code, 2)
            payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["strict_ok"])
            self.assertFalse(payload["cen03_incident_packages_check"]["ok"])
            self.assertIn("CEN-03-INC-STRICT-001", payload["cen03_incident_evidence_index"]["index"])

    def test_main_strict_with_local_incomplete_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_dir = root / "ovr-stab-qa-evidence-qa"
            readiness_dir = root / "ovr-stab-g8-readiness-ready"
            out_dir = root / "bundle-out"
            preopen_dir = out_dir / "preopen"
            qa_dir.mkdir(parents=True, exist_ok=True)
            readiness_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            preopen_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = Path(__file__).resolve().parent / "fixtures" / "field_report_real_integration.json"

            for rel in ("summary.csv", "summary.md", "summary.manifest.json", "target_protocols.manifest.json", "target_protocols.checklist.md"):
                (qa_dir / rel).write_text("ok\n", encoding="utf-8")
            (qa_dir / "summary.manifest.json").write_text(json.dumps({"strict_ok": True}), encoding="utf-8")
            (readiness_dir / "summary.manifest.json").write_text(
                json.dumps({"g8_ready": False, "scenario_results": [{"scenario_id": "CEN-05", "status": "FAIL"}]}),
                encoding="utf-8",
            )
            (preopen_dir / "summary.manifest.json").write_text(
                json.dumps({"preflight_ok": True, "operational_messages": ["PREOPEN-GO"]}),
                encoding="utf-8",
            )
            (preopen_dir / "summary.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")

            def fake_latest(prefix: str) -> Path | None:
                if prefix == "overlay-ws-stress-regression":
                    return None
                if prefix == "ovr-stab-qa-evidence":
                    return qa_dir
                if prefix == "ovr-stab-g8-readiness":
                    return readiness_dir
                return None

            def fake_run(cmd: list[str], run_out_dir: Path, step_id: str) -> dict[str, object]:
                (run_out_dir / f"{step_id}.stdout.log").write_text("ok\n", encoding="utf-8")
                (run_out_dir / f"{step_id}.stderr.log").write_text("", encoding="utf-8")
                (run_out_dir / "preopen.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")
                pre_dir = run_out_dir / "preopen"
                pre_dir.mkdir(parents=True, exist_ok=True)
                (pre_dir / "summary.manifest.json").write_text(
                    json.dumps(
                        {
                            "preflight_ok": True,
                            "preopen_status_code": "PREOPEN_GO",
                            "checks": [{"check_id": "artifacts", "status": "PASS", "preopen_status_code": "OK", "details": "ok", "next_step": "nenhum"}],
                            "next_actions": [{"priority": 1, "check_id": "go-live", "status_code": "PREOPEN_GO", "action": "iniciar", "command": "python scripts/run_ovr_stab_field_qa.py", "exit_criteria": "ok"}],
                            "operational_messages": ["PREOPEN-GO"],
                        }
                    ),
                    encoding="utf-8",
                )
                if step_id == "step_04_cen04_matrix_audit":
                    audit_dir = run_out_dir / "cen04-matrix-audit"
                    audit_dir.mkdir(parents=True, exist_ok=True)
                    (audit_dir / "summary.manifest.json").write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
                return {"id": step_id, "ok": True, "exit_code": 0}

            with (
                mock.patch.object(runner, "_latest_dir", side_effect=fake_latest),
                mock.patch.object(runner, "_run", side_effect=fake_run),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_ovr_stab_field_bundle.py",
                        "--skip-stress",
                        "--strict",
                        "--out-dir",
                        str(out_dir),
                        "--field-report",
                        str(fixture_path),
                    ],
                ),
            ):
                code = runner.main()
            self.assertEqual(code, 2)
            payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["cen05_field_report_check"]["ok"])

    def test_main_strict_with_local_complete_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_dir = root / "ovr-stab-qa-evidence-qa"
            readiness_dir = root / "ovr-stab-g8-readiness-ready"
            out_dir = root / "bundle-out"
            preopen_dir = out_dir / "preopen"
            qa_dir.mkdir(parents=True, exist_ok=True)
            readiness_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            preopen_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = Path(__file__).resolve().parent / "fixtures" / "field_report_real_complete_integration.json"

            for rel in ("summary.csv", "summary.md", "summary.manifest.json", "target_protocols.manifest.json", "target_protocols.checklist.md"):
                (qa_dir / rel).write_text("ok\n", encoding="utf-8")
            (qa_dir / "summary.manifest.json").write_text(json.dumps({"strict_ok": True}), encoding="utf-8")
            (readiness_dir / "summary.manifest.json").write_text(
                json.dumps({"g8_ready": True, "scenario_results": [{"scenario_id": "CEN-05", "status": "PASS"}]}),
                encoding="utf-8",
            )
            (preopen_dir / "summary.manifest.json").write_text(
                json.dumps({"preflight_ok": True, "operational_messages": ["PREOPEN-GO"]}),
                encoding="utf-8",
            )
            (preopen_dir / "summary.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")

            def fake_latest(prefix: str) -> Path | None:
                if prefix == "overlay-ws-stress-regression":
                    return None
                if prefix == "ovr-stab-qa-evidence":
                    return qa_dir
                if prefix == "ovr-stab-g8-readiness":
                    return readiness_dir
                return None

            def fake_run(cmd: list[str], run_out_dir: Path, step_id: str) -> dict[str, object]:
                (run_out_dir / f"{step_id}.stdout.log").write_text("ok\n", encoding="utf-8")
                (run_out_dir / f"{step_id}.stderr.log").write_text("", encoding="utf-8")
                (run_out_dir / "preopen.md").write_text("# CEN-05 preflight validator\n", encoding="utf-8")
                pre_dir = run_out_dir / "preopen"
                pre_dir.mkdir(parents=True, exist_ok=True)
                (pre_dir / "summary.manifest.json").write_text(
                    json.dumps(
                        {
                            "preflight_ok": True,
                            "preopen_status_code": "PREOPEN_GO",
                            "checks": [{"check_id": "artifacts", "status": "PASS", "preopen_status_code": "OK", "details": "ok", "next_step": "nenhum"}],
                            "next_actions": [{"priority": 1, "check_id": "go-live", "status_code": "PREOPEN_GO", "action": "iniciar", "command": "python scripts/run_ovr_stab_field_qa.py", "exit_criteria": "ok"}],
                            "operational_messages": ["PREOPEN-GO"],
                        }
                    ),
                    encoding="utf-8",
                )
                if step_id == "step_04_cen04_matrix_audit":
                    audit_dir = run_out_dir / "cen04-matrix-audit"
                    audit_dir.mkdir(parents=True, exist_ok=True)
                    (audit_dir / "summary.manifest.json").write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
                return {"id": step_id, "ok": True, "exit_code": 0}

            with (
                mock.patch.object(runner, "_latest_dir", side_effect=fake_latest),
                mock.patch.object(runner, "_run", side_effect=fake_run),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_ovr_stab_field_bundle.py",
                        "--skip-stress",
                        "--strict",
                        "--out-dir",
                        str(out_dir),
                        "--field-report",
                        str(fixture_path),
                    ],
                ),
            ):
                code = runner.main()
            self.assertEqual(code, 0)
            payload = json.loads((out_dir / "summary.manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["strict_ok"])
            self.assertTrue(payload["cen05_field_report_check"]["ok"])


if __name__ == "__main__":
    unittest.main()
