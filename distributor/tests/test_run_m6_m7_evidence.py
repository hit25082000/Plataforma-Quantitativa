"""Tests for M6/M7 evidence orchestrator helpers."""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_m6_m7_evidence.py"
    spec = importlib.util.spec_from_file_location("run_m6_m7_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module()


class TestRunM6M7Evidence(unittest.TestCase):
    def test_parse_binary_list(self) -> None:
        self.assertEqual(runner.parse_binary_list("0,1,0", "x"), [0, 1, 0])
        with self.assertRaises(ValueError):
            runner.parse_binary_list("2", "x")

    def test_parse_token_list(self) -> None:
        self.assertEqual(runner.parse_token_list(" baseline, pinned ", "x"), ["baseline", "pinned"])
        with self.assertRaises(ValueError):
            runner.parse_token_list(" , ", "x")

    def test_parse_positive_int(self) -> None:
        self.assertEqual(runner.parse_positive_int("1", "x"), 1)
        self.assertEqual(runner.parse_positive_int("7", "x"), 7)
        with self.assertRaises(ValueError):
            runner.parse_positive_int("0", "x")

    def test_parse_positive_float(self) -> None:
        self.assertEqual(runner.parse_positive_float("0.5", "x"), 0.5)
        self.assertEqual(runner.parse_positive_float("3", "x"), 3.0)
        with self.assertRaises(ValueError):
            runner.parse_positive_float("0", "x")

    def test_parse_non_negative_int(self) -> None:
        self.assertEqual(runner.parse_non_negative_int("0", "x"), 0)
        self.assertEqual(runner.parse_non_negative_int("9", "x"), 9)
        with self.assertRaises(ValueError):
            runner.parse_non_negative_int("-1", "x")

    def test_parse_optional_non_negative_int(self) -> None:
        self.assertEqual(runner.parse_optional_non_negative_int("-1", "x"), -1)
        self.assertEqual(runner.parse_optional_non_negative_int("0", "x"), 0)
        with self.assertRaises(ValueError):
            runner.parse_optional_non_negative_int("-2", "x")

    def test_resolve_window_seconds(self) -> None:
        self.assertEqual(
            runner.resolve_window_seconds(total_seconds=7200, window_seconds=3600, windows=2),
            3600.0,
        )
        self.assertEqual(
            runner.resolve_window_seconds(total_seconds=0, window_seconds=1800, windows=3),
            1800.0,
        )

    def test_resolve_hft_window_seconds(self) -> None:
        self.assertEqual(
            runner.resolve_hft_window_seconds(
                total_seconds=7200,
                window_seconds=3600,
                windows=2,
                scenario_count=4,
                run_count=2,
            ),
            450.0,
        )
        self.assertEqual(
            runner.resolve_hft_window_seconds(
                total_seconds=0,
                window_seconds=1800,
                windows=3,
                scenario_count=2,
                run_count=2,
            ),
            1800.0,
        )

    def test_can_resume_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            csv_path = root / "summary.csv"
            manifest_path = root / "summary.manifest.json"

            self.assertFalse(runner._can_resume_artifact(csv_path, manifest_path))

            csv_path.write_text("", encoding="utf-8")
            manifest_path.write_text("{}", encoding="utf-8")
            self.assertFalse(runner._can_resume_artifact(csv_path, manifest_path))

            csv_path.write_text("section,scenario\n", encoding="utf-8")
            self.assertFalse(runner._can_resume_artifact(csv_path, manifest_path))

            csv_path.write_text("section,scenario\nHFT,lp0-numa_auto\n", encoding="utf-8")
            manifest_path.write_text(
                '{"checks":[{"run":"pinned","metric":"shm_write_trade_duration","status":"ok"}]}',
                encoding="utf-8",
            )
            self.assertTrue(runner._can_resume_artifact(csv_path, manifest_path))

    def test_can_resume_artifact_validates_expected_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            csv_path = root / "summary.csv"
            manifest_path = root / "summary.manifest.json"
            csv_path.write_text("section,scenario\nHFT,lp0-numa_auto\n", encoding="utf-8")
            manifest_path.write_text(
                (
                    '{"checks":[{"run":"pinned","metric":"shm_write_trade_duration","status":"ok"}],'
                    '"args":{"runs":"baseline,pinned","shm_numa_node":0,"duration_seconds":60.0}}'
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                runner._can_resume_artifact(
                    csv_path,
                    manifest_path,
                    expected_args={"runs": "baseline,pinned", "shm_numa_node": 0},
                )
            )
            self.assertFalse(
                runner._can_resume_artifact(
                    csv_path,
                    manifest_path,
                    expected_args={"runs": "baseline,pinned", "shm_numa_node": 1},
                )
            )
            self.assertFalse(
                runner._can_resume_artifact(
                    csv_path,
                    manifest_path,
                    expected_args={"missing_key": "x"},
                )
            )

    def test_can_resume_artifact_session_requires_mode_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            csv_path = root / "session.csv"
            manifest_path = root / "session.manifest.json"

            csv_path.write_text("section,metric,value\nSESSION,gap_messages,0\n", encoding="utf-8")
            manifest_path.write_text(
                '{"mode":"session","result":{"session_ok":1},"args":{"session_seconds":120.0,"shm_name":"Local\\\\PQMarketDataV1"}}',
                encoding="utf-8",
            )
            self.assertTrue(runner._can_resume_artifact(csv_path, manifest_path))
            self.assertTrue(
                runner._can_resume_artifact(
                    csv_path,
                    manifest_path,
                    expected_args={"session_seconds": 120.0, "shm_name": "Local\\PQMarketDataV1"},
                )
            )
            self.assertFalse(
                runner._can_resume_artifact(
                    csv_path,
                    manifest_path,
                    expected_args={"session_seconds": 60.0},
                )
            )

    def test_should_reuse_existing_result(self) -> None:
        self.assertFalse(
            runner._should_reuse_existing_result(
                resume_requested=False,
                artifact_valid=True,
                eval_ok=True,
                resume_allow_failed=False,
            )
        )
        self.assertFalse(
            runner._should_reuse_existing_result(
                resume_requested=True,
                artifact_valid=False,
                eval_ok=True,
                resume_allow_failed=False,
            )
        )
        self.assertTrue(
            runner._should_reuse_existing_result(
                resume_requested=True,
                artifact_valid=True,
                eval_ok=True,
                resume_allow_failed=False,
            )
        )
        self.assertFalse(
            runner._should_reuse_existing_result(
                resume_requested=True,
                artifact_valid=True,
                eval_ok=False,
                resume_allow_failed=False,
            )
        )
        self.assertTrue(
            runner._should_reuse_existing_result(
                resume_requested=True,
                artifact_valid=True,
                eval_ok=False,
                resume_allow_failed=True,
            )
        )

    def test_evaluate_hft_manifest_ok(self) -> None:
        manifest = {
            "checks": [
                {
                    "run": "pinned",
                    "metric": "shm_write_trade_duration",
                    "status": "ok",
                    "reason": "ok",
                    "actual_p99_ns": 5000,
                    "actual_p999_ns": 7000,
                    "target_p99_ns": 10000,
                    "target_p999_ns": 20000,
                }
            ]
        }
        info = runner.evaluate_hft_manifest(manifest, exit_code=0, check_run="pinned", check_metric="shm_write_trade_duration")
        self.assertTrue(info["ok"])
        self.assertEqual(info["actual_p99_ns"], 5000)

    def test_evaluate_hft_manifest_fail(self) -> None:
        manifest = {
            "checks": [
                {
                    "run": "pinned",
                    "metric": "shm_write_trade_duration",
                    "status": "fail",
                    "reason": "p99_above_target",
                    "actual_p99_ns": 12000,
                    "actual_p999_ns": 22000,
                    "target_p99_ns": 10000,
                    "target_p999_ns": 20000,
                }
            ]
        }
        info = runner.evaluate_hft_manifest(manifest, exit_code=0, check_run="pinned", check_metric="shm_write_trade_duration")
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "p99_above_target")

    def test_evaluate_hft_manifest_exit_code_has_priority(self) -> None:
        manifest = {
            "checks": [
                {
                    "run": "pinned",
                    "metric": "shm_write_trade_duration",
                    "status": "ok",
                    "reason": "ok",
                    "actual_p99_ns": 5000,
                    "actual_p999_ns": 7000,
                    "target_p99_ns": 10000,
                    "target_p999_ns": 20000,
                }
            ]
        }
        info = runner.evaluate_hft_manifest(manifest, exit_code=3, check_run="pinned", check_metric="shm_write_trade_duration")
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "exit_code_3")

    def test_evaluate_hft_manifest_preserves_check_reason_when_already_failed(self) -> None:
        manifest = {
            "checks": [
                {
                    "run": "pinned",
                    "metric": "shm_write_trade_duration",
                    "status": "fail",
                    "reason": "market_not_connected",
                    "actual_p99_ns": -1,
                    "actual_p999_ns": -1,
                    "target_p99_ns": 10000,
                    "target_p999_ns": 20000,
                }
            ]
        }
        info = runner.evaluate_hft_manifest(manifest, exit_code=1, check_run="pinned", check_metric="shm_write_trade_duration")
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "market_not_connected")

    def test_aggregate_hft_results(self) -> None:
        rows = [
            {
                "scenario": "lp0-numa_auto",
                "ok": True,
                "reason": "ok",
                "exit_code": 0,
                "elapsed_s": 1.2,
                "actual_p99_ns": 100,
                "actual_p999_ns": 120,
                "target_p99_ns": 1000,
                "target_p999_ns": 2000,
                "check_run": "pinned",
                "check_metric": "shm_write_trade_duration",
                "artifact_csv": "a.csv",
                "artifact_manifest": "a.manifest.json",
                "stdout_log": "a.stdout.log",
                "stderr_log": "a.stderr.log",
                "skipped_existing": False,
            },
            {
                "scenario": "lp0-numa_auto",
                "ok": False,
                "reason": "check_failed",
                "exit_code": 2,
                "elapsed_s": 1.8,
                "actual_p99_ns": 300,
                "actual_p999_ns": 420,
                "target_p99_ns": 1000,
                "target_p999_ns": 2000,
                "check_run": "pinned",
                "check_metric": "shm_write_trade_duration",
                "artifact_csv": "b.csv",
                "artifact_manifest": "b.manifest.json",
                "stdout_log": "b.stdout.log",
                "stderr_log": "b.stderr.log",
                "skipped_existing": True,
            },
        ]
        info = runner.aggregate_hft_results(rows)
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["scenario"], "lp0-numa_auto")
        self.assertFalse(info[0]["ok"])
        self.assertEqual(info[0]["reason"], "check_failed")
        self.assertEqual(info[0]["window_count"], 2)
        self.assertEqual(info[0]["failed_windows"], 1)
        self.assertEqual(info[0]["max_actual_p99_ns"], 300)
        self.assertEqual(info[0]["max_actual_p999_ns"], 420)
        self.assertEqual(info[0]["exit_code"], 2)
        self.assertEqual(info[0]["skipped_existing_windows"], 1)

    def test_evaluate_hft_aggregate_gates(self) -> None:
        rows = [
            {
                "scenario": "lp0-numa_auto",
                "failed_windows": 0,
                "max_actual_p99_ns": 900,
                "max_actual_p999_ns": 1800,
            }
        ]
        disabled = runner.evaluate_hft_aggregate_gates(
            rows,
            max_failed_windows=-1,
            max_p99_ns=-1,
            max_p999_ns=-1,
        )
        self.assertFalse(disabled["enabled"])
        self.assertTrue(disabled["ok"])

        ok = runner.evaluate_hft_aggregate_gates(
            rows,
            max_failed_windows=0,
            max_p99_ns=1000,
            max_p999_ns=2000,
        )
        self.assertTrue(ok["enabled"])
        self.assertTrue(ok["ok"])

        fail = runner.evaluate_hft_aggregate_gates(
            rows,
            max_failed_windows=0,
            max_p99_ns=800,
            max_p999_ns=2000,
        )
        self.assertFalse(fail["ok"])
        self.assertEqual(fail["failed_gate"], "max_p99_ns")
        self.assertEqual(fail["failed_scenario"], "lp0-numa_auto")

    def test_is_non_fatal_failure_reason(self) -> None:
        self.assertTrue(runner.is_non_fatal_failure_reason("market_not_connected"))
        self.assertTrue(runner.is_non_fatal_failure_reason(" MARKET_NOT_CONNECTED "))
        self.assertFalse(runner.is_non_fatal_failure_reason("session_gate_failed"))

    def test_should_fail_on_any_ignores_market_not_connected(self) -> None:
        blocked = runner.should_fail_on_any(
            hft_rows=[{"ok": False, "reason": "market_not_connected"}],
            ipc_rows=[{"ok": True, "reason": "ok"}],
            hft_aggregate_gate={"enabled": False, "ok": True},
            ipc_aggregate_gate={"enabled": False, "ok": True},
        )
        self.assertFalse(blocked)

    def test_should_fail_on_any_blocks_regular_failures(self) -> None:
        blocked = runner.should_fail_on_any(
            hft_rows=[{"ok": False, "reason": "p99_above_target"}],
            ipc_rows=[],
            hft_aggregate_gate={"enabled": False, "ok": True},
            ipc_aggregate_gate={"enabled": False, "ok": True},
        )
        self.assertTrue(blocked)

    def test_should_fail_on_any_blocks_enabled_failed_gate(self) -> None:
        blocked = runner.should_fail_on_any(
            hft_rows=[{"ok": True, "reason": "ok"}],
            ipc_rows=[{"ok": True, "reason": "ok"}],
            hft_aggregate_gate={"enabled": True, "ok": False},
            ipc_aggregate_gate={"enabled": False, "ok": True},
        )
        self.assertTrue(blocked)

    def test_evaluate_ipc_session_manifest(self) -> None:
        manifest = {
            "mode": "session",
            "result": {
                "session_ok": 1,
                "gap_messages": 0,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 100,
            },
        }
        info = runner.evaluate_ipc_session_manifest(manifest, exit_code=0)
        self.assertTrue(info["ok"])
        self.assertEqual(info["session_ok"], 1)

        fail = runner.evaluate_ipc_session_manifest({"mode": "session", "result": {"session_ok": 0}}, exit_code=0)
        self.assertFalse(fail["ok"])
        self.assertEqual(fail["reason"], "session_gate_failed")

    def test_aggregate_ipc_results_ok(self) -> None:
        rows = [
            {
                "ok": True,
                "reason": "ok",
                "exit_code": 0,
                "elapsed_s": 1.5,
                "gap_messages": 0,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 10,
                "session_ok": 1,
                "max_gap_messages_allowed": 0,
                "max_ring_dropped_allowed": 0,
                "max_committed_mismatch_allowed": 0,
                "max_crc_mismatch_allowed": 0,
                "max_payload_mismatch_allowed": 0,
                "min_observed_trades_allowed": 0,
                "artifact_csv": "a.csv",
                "artifact_manifest": "a.manifest.json",
                "stdout_log": "a.stdout.log",
                "stderr_log": "a.stderr.log",
                "skipped_existing": False,
            },
            {
                "ok": True,
                "reason": "ok",
                "exit_code": 0,
                "elapsed_s": 2.5,
                "gap_messages": 1,
                "ring_dropped_delta": 2,
                "committed_mismatch": 3,
                "crc_mismatch": 4,
                "payload_mismatch": 5,
                "observed_trades": 20,
                "session_ok": 1,
                "max_gap_messages_allowed": 0,
                "max_ring_dropped_allowed": 0,
                "max_committed_mismatch_allowed": 0,
                "max_crc_mismatch_allowed": 0,
                "max_payload_mismatch_allowed": 0,
                "min_observed_trades_allowed": 0,
                "artifact_csv": "b.csv",
                "artifact_manifest": "b.manifest.json",
                "stdout_log": "b.stdout.log",
                "stderr_log": "b.stderr.log",
                "skipped_existing": True,
            },
        ]
        info = runner.aggregate_ipc_results(rows)
        self.assertTrue(info["ok"])
        self.assertEqual(info["window_count"], 2)
        self.assertEqual(info["gap_messages"], 1)
        self.assertEqual(info["ring_dropped_delta"], 2)
        self.assertEqual(info["committed_mismatch"], 3)
        self.assertEqual(info["crc_mismatch"], 4)
        self.assertEqual(info["payload_mismatch"], 5)
        self.assertEqual(info["observed_trades"], 30)
        self.assertEqual(info["skipped_existing_windows"], 1)
        self.assertEqual(info["artifact_csv"], "a.csv")

    def test_aggregate_ipc_results_fail(self) -> None:
        rows = [
            {
                "ok": True,
                "reason": "ok",
                "exit_code": 0,
                "elapsed_s": 1.0,
                "gap_messages": 0,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 10,
                "session_ok": 1,
                "max_gap_messages_allowed": 0,
                "max_ring_dropped_allowed": 0,
                "max_committed_mismatch_allowed": 0,
                "max_crc_mismatch_allowed": 0,
                "max_payload_mismatch_allowed": 0,
                "min_observed_trades_allowed": 0,
                "artifact_csv": "a.csv",
                "artifact_manifest": "a.manifest.json",
                "stdout_log": "a.stdout.log",
                "stderr_log": "a.stderr.log",
                "skipped_existing": False,
            },
            {
                "ok": False,
                "reason": "session_gate_failed",
                "exit_code": 2,
                "elapsed_s": 1.0,
                "gap_messages": 1,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 1,
                "session_ok": 0,
                "max_gap_messages_allowed": 0,
                "max_ring_dropped_allowed": 0,
                "max_committed_mismatch_allowed": 0,
                "max_crc_mismatch_allowed": 0,
                "max_payload_mismatch_allowed": 0,
                "min_observed_trades_allowed": 0,
                "artifact_csv": "b.csv",
                "artifact_manifest": "b.manifest.json",
                "stdout_log": "b.stdout.log",
                "stderr_log": "b.stderr.log",
                "skipped_existing": False,
            },
        ]
        info = runner.aggregate_ipc_results(rows)
        self.assertFalse(info["ok"])
        self.assertEqual(info["reason"], "session_gate_failed")
        self.assertEqual(info["exit_code"], 2)
        self.assertEqual(info["session_ok"], 0)

    def test_evaluate_ipc_aggregate_gates_disabled(self) -> None:
        ipc = {
            "gap_messages": 5,
            "ring_dropped_delta": 6,
            "committed_mismatch": 7,
            "crc_mismatch": 8,
            "payload_mismatch": 9,
            "observed_trades": 10,
        }
        gate = runner.evaluate_ipc_aggregate_gates(
            ipc,
            max_gap_messages=-1,
            max_ring_dropped=-1,
            max_committed_mismatch=-1,
            max_crc_mismatch=-1,
            max_payload_mismatch=-1,
            min_observed_trades=-1,
        )
        self.assertFalse(gate["enabled"])
        self.assertTrue(gate["ok"])
        self.assertEqual(gate["reason"], "disabled")

    def test_evaluate_ipc_aggregate_gates_fail_and_unknown(self) -> None:
        fail = runner.evaluate_ipc_aggregate_gates(
            {
                "gap_messages": 10,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 100,
            },
            max_gap_messages=5,
            max_ring_dropped=-1,
            max_committed_mismatch=-1,
            max_crc_mismatch=-1,
            max_payload_mismatch=-1,
            min_observed_trades=-1,
        )
        self.assertTrue(fail["enabled"])
        self.assertFalse(fail["ok"])
        self.assertEqual(fail["failed_gate"], "max_gap_messages")
        self.assertEqual(fail["reason"], "max_gap_messages_failed")

        unknown = runner.evaluate_ipc_aggregate_gates(
            {
                "gap_messages": -1,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 100,
            },
            max_gap_messages=0,
            max_ring_dropped=-1,
            max_committed_mismatch=-1,
            max_crc_mismatch=-1,
            max_payload_mismatch=-1,
            min_observed_trades=-1,
        )
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["reason"], "max_gap_messages_unknown")

    def test_execute_with_retries(self) -> None:
        attempts = {"count": 0}

        def _run_once() -> dict:
            attempts["count"] += 1
            return {"ok": attempts["count"] >= 2, "value": attempts["count"]}

        result = runner.execute_with_retries(
            run_once=_run_once,
            is_ok=lambda item: bool(item.get("ok")),
            max_retries=3,
            retry_delay_seconds=0.0,
        )
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["retried"])
        self.assertTrue(result["ok"])

    def test_write_summary_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            csv_path = root / "summary.csv"
            md_path = root / "summary.md"
            hft_rows = [
                {
                    "scenario": "lp0-numa_auto",
                    "window_index": 1,
                    "skipped_existing": False,
                    "attempts": 2,
                    "retried": True,
                    "ok": True,
                    "exit_code": 0,
                    "reason": "ok",
                    "check_run": "pinned",
                    "check_metric": "shm_write_trade_duration",
                    "actual_p99_ns": 100,
                    "actual_p999_ns": 200,
                    "target_p99_ns": 1000,
                    "target_p999_ns": 2000,
                    "artifact_csv": "hft.csv",
                    "artifact_manifest": "hft.manifest.json",
                }
            ]
            ipc_rows = [
                {
                    "scenario": "session",
                    "window_index": 1,
                    "skipped_existing": False,
                    "attempts": 1,
                    "retried": False,
                    "ok": True,
                    "exit_code": 0,
                    "reason": "ok",
                    "gap_messages": 0,
                    "ring_dropped_delta": 0,
                    "committed_mismatch": 0,
                    "crc_mismatch": 0,
                    "payload_mismatch": 0,
                    "observed_trades": 10,
                    "artifact_csv": "session.csv",
                    "artifact_manifest": "session.manifest.json",
                }
            ]
            ipc_aggregate_row = {
                "ok": True,
                "exit_code": 0,
                "reason": "ok",
                "gap_messages": 0,
                "ring_dropped_delta": 0,
                "committed_mismatch": 0,
                "crc_mismatch": 0,
                "payload_mismatch": 0,
                "observed_trades": 10,
                "artifact_csv": "session.csv",
                "artifact_manifest": "session.manifest.json",
            }
            gate = {
                "enabled": True,
                "ok": True,
                "reason": "ok",
                "max_gap_messages": 0,
                "max_ring_dropped": 0,
                "max_committed_mismatch": 0,
                "max_crc_mismatch": 0,
                "max_payload_mismatch": 0,
                "min_observed_trades": 0,
            }
            hft_aggregate_rows = [
                {
                    "scenario": "lp0-numa_auto",
                    "window_count": 1,
                    "failed_windows": 0,
                    "ok": True,
                    "reason": "ok",
                    "max_actual_p99_ns": 100,
                    "max_actual_p999_ns": 200,
                    "target_p99_ns": 1000,
                    "target_p999_ns": 2000,
                    "check_run": "pinned",
                    "check_metric": "shm_write_trade_duration",
                    "artifact_csv": "hft.csv",
                    "artifact_manifest": "hft.manifest.json",
                    "skipped_existing_windows": 0,
                }
            ]
            hft_gate = {
                "enabled": True,
                "ok": True,
                "reason": "ok",
                "failed_gate": "",
                "failed_scenario": "",
                "max_failed_windows": 0,
                "max_p99_ns": 1000,
                "max_p999_ns": 2000,
            }

            runner.write_summary_csv(
                csv_path,
                hft_rows,
                ipc_rows,
                ipc_aggregate_row,
                overall_ok=True,
                hft_aggregate_rows=hft_aggregate_rows,
                hft_aggregate_gate=hft_gate,
            )
            runner.write_summary_markdown(
                md_path,
                hft_rows=hft_rows,
                hft_aggregate_rows=hft_aggregate_rows,
                hft_aggregate_gate=hft_gate,
                ipc_rows=ipc_rows,
                ipc_result=ipc_aggregate_row,
                ipc_aggregate=gate,
                overall_ok=True,
            )

            csv_text = csv_path.read_text(encoding="utf-8")
            md_text = md_path.read_text(encoding="utf-8")
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            expected_cols = len(rows[0])
            for row in rows[1:]:
                self.assertEqual(len(row), expected_cols)

            self.assertIn("section,scenario,window_index,skipped_existing,attempts,retried,ok", csv_text)
            self.assertIn("HFT,lp0-numa_auto,1,0,2,1,1,0,ok", csv_text)
            self.assertIn("HFT_AGGREGATE,lp0-numa_auto", csv_text)
            self.assertIn("HFT_AGGREGATE_GATE,all", csv_text)
            self.assertIn("IPC_AGGREGATE,session", csv_text)
            self.assertIn("# M6/M7 Evidence Summary", md_text)
            self.assertIn("aggregate_gate_ok: `1`", md_text)


if __name__ == "__main__":
    unittest.main()
