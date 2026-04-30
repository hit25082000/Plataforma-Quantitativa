from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_ovr_stab_qa_evidence.py"
    spec = importlib.util.spec_from_file_location("run_ovr_stab_qa_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module()


class TestRunOvrStabQaEvidence(unittest.TestCase):
    def test_cen05_threshold_contract_matches_stress_script(self) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        stress_path = root / "scripts" / "run_overlay_ws_stress_regression.py"
        spec = importlib.util.spec_from_file_location("run_overlay_ws_stress_regression_contract", stress_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module from {stress_path}")
        stress_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = stress_module
        spec.loader.exec_module(stress_module)

        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["queue_max"]["value"],
            stress_module.evaluate([{"scenario": "x", "queue_max": 1, "latency_p95_ms": 0, "latency_p99_ms": 0, "published_count": 1, "consumer_fps": 100, "backlog_growth_ratio": 1, "publish_rate_floor_ratio": 1, "publish_rate_overshoot_ratio": 1, "publish_interval_jitter_cv": 0}])["thresholds"]["queue_max"],
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["latency_p95_ms"]["value"],
            stress_module.LATENCY_P95_MAX_MS,
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["latency_p99_ms"]["value"],
            stress_module.LATENCY_P99_MAX_MS,
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["backlog_growth_ratio"]["value"],
            stress_module.BACKLOG_GROWTH_RATIO_MAX,
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["consumer_fps"]["value"],
            stress_module.CONSUMER_FPS_MIN,
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["publish_rate_floor_ratio"]["value"],
            stress_module.PUBLISH_RATE_FLOOR_FACTOR_MIN,
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["publish_rate_overshoot_ratio"]["value"],
            stress_module.PUBLISH_RATE_OVERSHOOT_FACTOR_MAX,
        )
        self.assertEqual(
            runner.CEN05_LOAD_THRESHOLD_CONTRACT["publish_interval_jitter_cv"]["value"],
            stress_module.PUBLISH_INTERVAL_JITTER_CV_MAX,
        )

    def test_build_ovr_status_maps_partial_done(self) -> None:
        rows = [
            {"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-01", "OVR-STAB-OBS-09"]},
            {"id": "suite-b", "ok": True, "ovr": ["OVR-STAB-QA-02"]},
        ]
        status = runner.build_ovr_status(rows)
        self.assertEqual(status["OVR-STAB-QA-01"]["state"], "partial-done")
        self.assertEqual(status["OVR-STAB-QA-02"]["state"], "partial-done")
        self.assertEqual(status["OVR-STAB-QA-04"]["state"], "not-covered")

    def test_build_ovr_status_detects_blocked(self) -> None:
        rows = [{"id": "suite-a", "ok": False, "ovr": ["OVR-STAB-QA-03"]}]
        status = runner.build_ovr_status(rows)
        self.assertEqual(status["OVR-STAB-QA-03"]["state"], "partial-blocked")

    def test_write_summary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "summary.csv"
            md_path = root / "summary.md"
            rows = [
                {
                    "id": "suite-a",
                    "ok": True,
                    "exit_code": 0,
                    "elapsed_s": 0.2,
                    "ovr": ["OVR-STAB-QA-01", "OVR-STAB-OBS-09"],
                    "stdout_log": "a.stdout.log",
                    "stderr_log": "a.stderr.log",
                }
            ]
            status = runner.build_ovr_status(rows)
            runner.write_summary_csv(csv_path, rows)
            runner.write_summary_md(md_path, rows, status, overall_ok=True)
            csv_text = csv_path.read_text(encoding="utf-8")
            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("suite_id,ok,exit_code,elapsed_s", csv_text)
            self.assertIn("suite-a", csv_text)
            self.assertIn("# OVR STAB QA Evidence (Local)", md_text)
            self.assertIn("OVR-STAB-QA-01", md_text)

    def test_target_templates_include_field_tasks(self) -> None:
        rows = [{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-01"]}]
        templates = runner.build_target_templates(rows)
        self.assertIn("OVR-STAB-AUD-04", templates)
        self.assertIn("OVR-STAB-AUD-05", templates)
        self.assertIn("OVR-STAB-QA-03", templates)
        self.assertIn("OVR-STAB-QA-04", templates)
        self.assertIn("OVR-STAB-QA-05", templates)
        self.assertIn("OVR-STAB-OBS-09", templates)
        self.assertEqual(templates["OVR-STAB-OBS-09"]["evidence_state"], "ready-local")
        self.assertEqual(templates["OVR-STAB-QA-03"]["evidence_state"], "pending-field")
        self.assertEqual(templates["OVR-STAB-QA-04"]["evidence_state"], "pending-field")

    def test_target_protocol_files_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "target_protocols.manifest.json"
            checklist_path = root / "target_protocols.checklist.md"
            templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-02"]}])
            runner.write_target_protocols_manifest(manifest_path, templates)
            runner.write_target_protocols_checklist(checklist_path, templates)
            manifest_text = manifest_path.read_text(encoding="utf-8")
            checklist_text = checklist_path.read_text(encoding="utf-8")
            self.assertIn('"OVR-STAB-AUD-04"', manifest_text)
            self.assertIn('"artifact_naming"', manifest_text)
            self.assertIn("ovr-stab-<scenario_id>-<artifact_kind>-<utc_compact>.<ext>", manifest_text)
            self.assertIn('"cen05_threshold_contract"', manifest_text)
            self.assertIn("OVR-STAB-QA-03 - protocolo padronizado de injeção/observação", checklist_text)
            self.assertIn("operator_direct_flow", checklist_text)
            self.assertIn("baseline_check", checklist_text)
            self.assertIn("CEN-03 - exemplos prontos de incidente", checklist_text)
            self.assertIn("CEN-03-INC-EX-001", checklist_text)
            self.assertIn("OVR-STAB-QA-04 - matriz DPI", checklist_text)
            self.assertIn("OVR-STAB-QA-05", checklist_text)
            self.assertIn("CEN-05 (carga) - contrato objetivo de thresholds", checklist_text)
            self.assertIn("latency_p95_ms", checklist_text)
            self.assertIn("CEN-05 - execucao operacional imediata", checklist_text)
            self.assertIn("monitor-3", checklist_text)
            self.assertIn("OVR-STAB-QA-04 - passos de reproducao", checklist_text)
            self.assertIn("move_window_to_next_monitor", checklist_text)
            self.assertIn("OVR-STAB-QA-04 - coleta padronizada de drift", checklist_text)
            self.assertIn("drift_band", checklist_text)
            self.assertIn("CEN-02 (zoom/escala) - roteiro operacional objetivo", checklist_text)
            self.assertIn("python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-02 --require-ovr OVR-STAB-OBS-09", checklist_text)
            self.assertIn("python scripts/verify_ovr_stab_g8_readiness.py --qa-manifest", checklist_text)
            self.assertIn("CEN-02 - captura de transicoes obrigatorias", checklist_text)
            self.assertIn("CEN-02 - evidencia minima por transicao", checklist_text)
            self.assertIn("CEN-02 - contrato de qualidade automatizado", checklist_text)
            self.assertIn("required_transitions_count", checklist_text)
            self.assertIn("evidence_ref_coverage_ratio", checklist_text)
            self.assertIn("| SUSPECT | [ ] |", checklist_text)
            self.assertIn("| FROZEN | [ ] |", checklist_text)
            self.assertIn("| RECALIBRATING | [ ] |", checklist_text)
            self.assertIn("| SUSPECT |  |  |  |  | pass|fail|blocked |", checklist_text)
            self.assertIn("scenario_id", checklist_text)
            self.assertIn("symptom", checklist_text)
            self.assertIn("observed_signal", checklist_text)
            self.assertIn("resultado: pass|fail|blocked", checklist_text)

    def test_validate_target_protocols_requires_obs09_fields(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-01"]}])
        ok, errors = runner.validate_target_protocols(templates)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        qa04_template = templates["OVR-STAB-QA-04"]["execution_template"]
        self.assertIn("monitor_dpi_matrix", qa04_template)
        self.assertIn("reproduction_steps", qa04_template)
        self.assertIn("drift_collection_required_fields", qa04_template)
        aud05_template = templates["OVR-STAB-AUD-05"]["execution_template"]
        self.assertIn("cen02_execution_steps", aud05_template)
        self.assertIn("cen02_required_transitions", aud05_template)
        self.assertIn("cen02_transition_required_fields", aud05_template)
        self.assertIn("cen02_step_required_fields", aud05_template)
        self.assertIn("cen02_quality_gates", aud05_template)

        templates["OVR-STAB-OBS-09"]["execution_template"]["required_notes"] = ["scenario"]
        ok2, errors2 = runner.validate_target_protocols(templates)
        self.assertFalse(ok2)
        self.assertTrue(any("scenario_id" in err for err in errors2))
        self.assertTrue(any("symptom" in err for err in errors2))
        self.assertTrue(any("observed_signal" in err for err in errors2))

    def test_enforce_required_ovr_local_mode_allows_qa04_not_covered(self) -> None:
        status = {
            "OVR-STAB-QA-01": {"state": "partial-done"},
            "OVR-STAB-QA-04": {"state": "not-covered"},
        }
        ok, errors = runner.enforce_required_ovr(status, ["OVR-STAB-QA-01", "OVR-STAB-QA-04"], "local")
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_enforce_required_ovr_field_mode_requires_partial_done(self) -> None:
        status = {"OVR-STAB-QA-04": {"state": "not-covered"}}
        ok, errors = runner.enforce_required_ovr(status, ["OVR-STAB-QA-04"], "field-ready")
        self.assertFalse(ok)
        self.assertTrue(any("not partial-done" in err for err in errors))

    def test_build_evidence_integrity_report_detects_missing_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "summary.csv").write_text("suite_id,ok,exit_code,elapsed_s,ovr_ids,stdout_log,stderr_log\n", encoding="utf-8")
            (out_dir / "summary.md").write_text("# summary\n", encoding="utf-8")
            (out_dir / "summary.manifest.json").write_text("{}", encoding="utf-8")
            (out_dir / "target_protocols.manifest.json").write_text("{}", encoding="utf-8")
            (out_dir / "target_protocols.checklist.md").write_text("# checklist\n", encoding="utf-8")
            rows = [{"id": "suite-a", "ok": False, "ovr": ["OVR-STAB-QA-01"]}]
            report = runner.build_evidence_integrity_report(rows, out_dir)
            self.assertFalse(report["ok"])
            self.assertFalse(report["row_count_match"])
            self.assertGreaterEqual(len(report["missing_suite_logs"]), 1)

    def test_validate_target_protocols_detects_qa04_matrix_gap(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-04"]}])
        templates["OVR-STAB-QA-04"]["execution_template"]["monitor_dpi_matrix"] = [
            {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open"}
        ]
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("monitor_dpi_matrix" in err for err in errors))

    def test_validate_target_protocols_detects_qa04_missing_matrix_fields(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-04"]}])
        templates["OVR-STAB-QA-04"]["execution_template"]["monitor_dpi_matrix"] = [
            {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open"},
            {"monitor_id": "monitor-2", "dpi_percent": 125},
            {"dpi_percent": 150, "transition": "move-to-monitor"},
        ]
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("missing field: transition" in err for err in errors))
        self.assertTrue(any("missing field: monitor_id" in err for err in errors))

    def test_validate_target_protocols_detects_qa04_duplicate_monitor_id(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-04"]}])
        templates["OVR-STAB-QA-04"]["execution_template"]["monitor_dpi_matrix"] = [
            {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open"},
            {"monitor_id": "monitor-1", "dpi_percent": 125, "transition": "move-to-monitor"},
            {"monitor_id": "monitor-3", "dpi_percent": 150, "transition": "move-to-monitor"},
        ]
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("duplicated monitor_id" in err for err in errors))

    def test_validate_target_protocols_detects_qa04_invalid_transition(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-04"]}])
        templates["OVR-STAB-QA-04"]["execution_template"]["monitor_dpi_matrix"] = [
            {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open"},
            {"monitor_id": "monitor-2", "dpi_percent": 125, "transition": "teleport"},
            {"monitor_id": "monitor-3", "dpi_percent": 150, "transition": "move-to-monitor"},
        ]
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("invalid transition" in err for err in errors))

    def test_validate_target_protocols_detects_qa04_non_integer_dpi(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-04"]}])
        templates["OVR-STAB-QA-04"]["execution_template"]["monitor_dpi_matrix"] = [
            {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open"},
            {"monitor_id": "monitor-2", "dpi_percent": "125x", "transition": "move-to-monitor"},
            {"monitor_id": "monitor-3", "dpi_percent": 150, "transition": "move-to-monitor"},
        ]
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("dpi_percent is not integer" in err for err in errors))

    def test_validate_target_protocols_detects_qa03_protocol_gaps(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-03"]}])
        qa03 = templates["OVR-STAB-QA-03"]["execution_template"]
        qa03["injection_protocol_steps"] = ["capture_baseline_axis_stable"]
        qa03["required_signals"]["hud"] = ["axis_status"]  # type: ignore[index]
        qa03["required_transitions"] = []
        qa03["incident_minimum_evidence"] = {"min_evidence_refs": 1}
        qa03["evidence_template_required_fields"] = ["scenario_id"]
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("missing injection protocol step" in err for err in errors))
        self.assertTrue(any("missing hud signal" in err for err in errors))
        self.assertTrue(any("missing required transition" in err for err in errors))
        self.assertTrue(any("min_evidence_refs" in err for err in errors))
        self.assertTrue(any("missing incident artifact kind" in err for err in errors))
        self.assertTrue(any("missing incident channel comparison" in err for err in errors))
        self.assertTrue(any("missing incident required field" in err for err in errors))
        self.assertTrue(any("missing evidence template field" in err for err in errors))

    def test_validate_target_protocols_detects_cen02_contract_gaps(self) -> None:
        templates = runner.build_target_templates([{"id": "suite-a", "ok": True, "ovr": ["OVR-STAB-QA-02"]}])
        aud05 = templates["OVR-STAB-AUD-05"]["execution_template"]
        aud05["cen02_required_transitions"] = ["SUSPECT"]
        aud05["cen02_transition_required_fields"] = ["transition_state", "event_timestamp_utc"]
        aud05["cen02_quality_gates"]["drift_px_max_after_stable"] = {"op": "<=", "value": 5.0}
        ok, errors = runner.validate_target_protocols(templates)
        self.assertFalse(ok)
        self.assertTrue(any("missing CEN-02 required transition: FROZEN" in err for err in errors))
        self.assertTrue(any("missing CEN-02 transition field: evidence_ref" in err for err in errors))
        self.assertTrue(any("invalid CEN-02 quality gate: drift_px_max_after_stable" in err for err in errors))

    def test_validate_trace_completeness_contract(self) -> None:
        ok, errors = runner.validate_trace_completeness_contract()
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_suite_failures_extracts_assertion_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "suite-a.stderr.log").write_text("AssertionError: boom\n", encoding="utf-8")
            rows = [{"id": "suite-a", "ok": False, "ovr": ["OVR-STAB-QA-03"]}]
            failures = runner.summarize_suite_failures(rows, out_dir)
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["failure_reason"], "assertion-failure")

    def test_build_ovr_blockers_links_failed_suites(self) -> None:
        rows = [
            {"id": "suite-a", "ok": False, "ovr": ["OVR-STAB-QA-01", "OVR-STAB-OBS-09"]},
            {"id": "suite-b", "ok": True, "ovr": ["OVR-STAB-QA-01"]},
        ]
        blockers = runner.build_ovr_blockers(rows)
        self.assertEqual(blockers["OVR-STAB-QA-01"], ["suite-a"])
        self.assertEqual(blockers["OVR-STAB-OBS-09"], ["suite-a"])

    def test_trace_contract_constants_cover_core_fields(self) -> None:
        self.assertIn("event_id", runner.TRACE_REQUIRED_SESSION_FIELDS)
        self.assertIn("frame_seq", runner.TRACE_REQUIRED_FRAME_FIELDS)
        self.assertIn("render_indicators", runner.TRACE_REQUIRED_FRAME_FIELDS)
        self.assertIn("line_count_visible", runner.TRACE_REQUIRED_RENDER_INDICATOR_FIELDS)
        self.assertIn("changed", runner.TRACE_REQUIRED_STATUS_TRANSITION_FIELDS)
        self.assertIn("STABLE->FROZEN|RECALIBRATING", runner.CEN03_REQUIRED_TRANSITIONS)
        self.assertEqual(runner.CEN03_INCIDENT_MIN_EVIDENCE["min_evidence_refs"], 3)
        self.assertGreaterEqual(len(runner.CEN03_OPERATOR_DIRECT_FLOW), 4)
        self.assertGreaterEqual(len(runner.CEN03_INCIDENT_EXAMPLES), 2)

    def test_validate_cen05_stress_manifest_requires_manifest(self) -> None:
        ok, errors, report = runner.validate_cen05_stress_manifest(None)
        self.assertFalse(ok)
        self.assertTrue(any("not provided" in err for err in errors))
        self.assertEqual(report, {})

    def test_validate_cen05_stress_manifest_accepts_valid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.manifest.json"
            payload = {
                "overall_ok": True,
                "rows": [
                    {
                        "scenario": "hf_240hz_always_diff",
                        "queue_max": 1,
                        "backlog_growth_ratio": 1.1,
                        "latency_p95_ms": 50.0,
                        "latency_p99_ms": 100.0,
                        "consumer_fps": 92.0,
                        "publish_rate_floor_ratio": 0.8,
                        "publish_rate_overshoot_ratio": 1.1,
                        "publish_interval_jitter_cv": 0.2,
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            ok, errors, report = runner.validate_cen05_stress_manifest(path)
            self.assertTrue(ok)
            self.assertEqual(errors, [])
            self.assertEqual(report["rows_checked"], 1)

    def test_validate_cen05_stress_manifest_rejects_latency_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.manifest.json"
            payload = {
                "overall_ok": True,
                "rows": [
                    {
                        "scenario": "hf_bad_latency",
                        "queue_max": 1,
                        "backlog_growth_ratio": 1.0,
                        "latency_p95_ms": 75.0,
                        "latency_p99_ms": 140.0,
                        "consumer_fps": 95.0,
                        "publish_rate_floor_ratio": 0.9,
                        "publish_rate_overshoot_ratio": 1.1,
                        "publish_interval_jitter_cv": 0.2,
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            ok, errors, _ = runner.validate_cen05_stress_manifest(path)
            self.assertFalse(ok)
            self.assertTrue(any("latency_p95_ms" in err for err in errors))
            self.assertTrue(any("latency_p99_ms" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
