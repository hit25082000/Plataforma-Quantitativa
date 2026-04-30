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
    path = root / "scripts" / "verify_cen05_preflight.py"
    spec = importlib.util.spec_from_file_location("verify_cen05_preflight", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module()


class TestVerifyCen05Preflight(unittest.TestCase):
    def test_check_artifacts_fails_when_manifest_missing(self) -> None:
        result = validator._check_artifacts(None)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("summary.manifest.json", result["missing"])

    def test_check_artifacts_fails_when_required_files_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            manifest = base / "summary.manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            result = validator._check_artifacts(manifest)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("stress.csv", result["missing"])

    def test_check_thresholds_passes_when_gate_and_overall_ok(self) -> None:
        manifest = {"overall_ok": True, "gate": {"ok": True, "failures": []}}
        result = validator._check_thresholds(manifest)
        self.assertEqual(result["status"], "PASS")

    def test_check_thresholds_lists_failures_when_gate_fails(self) -> None:
        manifest = {
            "overall_ok": False,
            "gate": {"ok": False, "failures": ["publish_rate_floor_ratio=0.41 < 0.75"]},
        }
        result = validator._check_thresholds(manifest)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["preopen_status_code"], "THRESHOLDS_GATE_FAILED")
        self.assertTrue(any("publish_rate_floor_ratio" in item for item in result["failures"]))

    def test_check_thresholds_fallback_when_failures_is_empty(self) -> None:
        manifest = {"overall_ok": False, "gate": {"ok": False, "failures": []}}
        result = validator._check_thresholds(manifest)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["failures"])

    def test_check_thresholds_fallback_when_failures_is_invalid(self) -> None:
        manifest = {"overall_ok": False, "gate": {"ok": False, "failures": "broken"}}
        result = validator._check_thresholds(manifest)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("gate.failures invalido", result["failures"])

    def test_check_commands_fails_on_missing_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            commands = Path(tmp) / "commands.ready.md"
            commands.write_text("# commands\npython scripts/run_overlay_ws_stress_regression.py\n", encoding="utf-8")
            result = validator._check_commands(commands)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("run_ovr_stab_qa_evidence.py", result["missing_snippets"])

    def test_check_env_doctor_passes_with_required_vars_paths_and_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dll_path = Path(tmp) / "ProfitChartTrading.dll"
            dll_path.write_text("ok", encoding="utf-8")
            with mock.patch.dict(
                validator.os.environ,
                {
                    "PROFIT_DLL_USER": "u",
                    "PROFIT_DLL_PASSWORD": "p",
                    "PQ_PROFIT_DLL_PATH": str(dll_path),
                },
                clear=False,
            ):
                with (
                    mock.patch.object(validator.platform, "system", return_value="Windows"),
                    mock.patch.object(validator.shutil, "which", return_value=r"C:\mock\bin.exe"),
                    mock.patch.object(validator.importlib.util, "find_spec", return_value=object()),
                    mock.patch.object(validator, "REQUIRED_OPENING_SCRIPT_PATHS", (dll_path,)),
                ):
                    result = validator._check_env_doctor(validator.REQUIRED_ENV_KEYS)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["preopen_status_code"], validator.PREOPEN_CHECK_CODE_OK)

    def test_check_env_doctor_fails_without_required_vars(self) -> None:
        with mock.patch.dict(
            validator.os.environ,
            {"PQ_PROFIT_DLL_PATH": r"C:\dll\ProfitChartTrading.dll"},
            clear=False,
        ):
            with (
                mock.patch.object(validator.platform, "system", return_value="Windows"),
                mock.patch.object(validator.shutil, "which", return_value=r"C:\mock\bin.exe"),
                mock.patch.object(validator.importlib.util, "find_spec", return_value=object()),
                mock.patch.object(validator, "REQUIRED_OPENING_SCRIPT_PATHS", tuple()),
            ):
                result = validator._check_env_doctor(validator.REQUIRED_ENV_KEYS)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("PROFIT_DLL_USER", result["missing_env"])
        self.assertTrue(any(row["failure_code"] == "ENV_VARS_MISSING" for row in result["remediation_plan"]))

    def test_check_env_doctor_fails_for_invalid_dll_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid_path = Path(tmp) / "not-a-dll.txt"
            invalid_path.write_text("x", encoding="utf-8")
            with mock.patch.dict(
                validator.os.environ,
                {
                    "PROFIT_DLL_USER": "u",
                    "PROFIT_DLL_PASSWORD": "p",
                    "PQ_PROFIT_DLL_PATH": str(invalid_path),
                },
                clear=False,
            ):
                with (
                    mock.patch.object(validator.platform, "system", return_value="Windows"),
                    mock.patch.object(validator.shutil, "which", return_value=r"C:\mock\bin.exe"),
                    mock.patch.object(validator.importlib.util, "find_spec", return_value=object()),
                    mock.patch.object(validator, "REQUIRED_OPENING_SCRIPT_PATHS", tuple()),
                ):
                    result = validator._check_env_doctor(validator.REQUIRED_ENV_KEYS)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("PQ_PROFIT_DLL_PATH", result["invalid_paths"])
        self.assertTrue(any(row["failure_code"] == "OPENING_PATHS_INVALID" for row in result["remediation_plan"]))

    def test_check_env_doctor_fails_for_missing_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dll_path = Path(tmp) / "ProfitChartTrading.dll"
            dll_path.write_text("ok", encoding="utf-8")
            with mock.patch.dict(
                validator.os.environ,
                {
                    "PROFIT_DLL_USER": "u",
                    "PROFIT_DLL_PASSWORD": "p",
                    "PQ_PROFIT_DLL_PATH": str(dll_path),
                },
                clear=False,
            ):
                with (
                    mock.patch.object(validator.platform, "system", return_value="Windows"),
                    mock.patch.object(validator.shutil, "which", side_effect=lambda name: None if name == "python" else r"C:\mock\bin.exe"),
                    mock.patch.object(validator.importlib.util, "find_spec", return_value=object()),
                    mock.patch.object(validator, "REQUIRED_OPENING_SCRIPT_PATHS", tuple()),
                ):
                    result = validator._check_env_doctor(validator.REQUIRED_ENV_KEYS)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("python:missing_executable", result["missing_dependencies"])
        self.assertTrue(any(row["failure_code"] == "OPENING_DEPENDENCIES_MISSING" for row in result["remediation_plan"]))

    def test_check_bundle_passes_when_strict_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "summary.manifest.json"
            manifest.write_text('{"strict_ok": true}', encoding="utf-8")
            result = validator._check_bundle(manifest, {"strict_ok": True})
            self.assertEqual(result["status"], "PASS")

    def test_check_readiness_fails_when_cen05_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "summary.manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            result = validator._check_readiness(
                manifest,
                {
                    "g8_ready": True,
                    "scenario_results": [
                        {
                            "scenario_id": "CEN-05",
                            "status": "FAIL",
                            "classification": "CONFIRMED_NOT_READY",
                            "diagnosis": "x",
                            "next_action": "y",
                            "diagnostics": {},
                        }
                    ],
                },
            )
            self.assertEqual(result["status"], "FAIL")

    def test_check_readiness_fails_when_contract_fields_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "summary.manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            result = validator._check_readiness(
                manifest,
                {"g8_ready": True, "scenario_results": [{"scenario_id": "CEN-05", "status": "PASS"}]},
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["preopen_status_code"], "READINESS_CONTRACT_INVALID")

    def test_check_freshness_fails_for_stale_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.json"
            old.write_text("{}", encoding="utf-8")
            with mock.patch.object(validator.time, "time", return_value=old.stat().st_mtime + 10_000):
                result = validator._check_freshness((("old", old),), 60)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(result["stale"])

    def test_build_operational_messages_includes_blocking_steps(self) -> None:
        checks = [
            {"check_id": "thresholds", "status": "FAIL", "next_step": "corrigir threshold"},
            {"check_id": "env_doctor", "status": "PASS", "next_step": "nenhum"},
        ]
        messages = validator._build_operational_messages(checks, preflight_ok=False)
        self.assertTrue(messages[0].startswith("PREOPEN-BLOCK"))
        self.assertTrue(any("THRESHOLDS:" in row for row in messages))

    def test_derive_preopen_status_code(self) -> None:
        self.assertEqual(
            validator._derive_preopen_status_code([], preflight_ok=True),
            validator.PREOPEN_STATUS_GO,
        )
        self.assertEqual(
            validator._derive_preopen_status_code([], preflight_ok=False),
            validator.PREOPEN_STATUS_BLOCKED,
        )

    def test_build_next_actions_for_blocked_preflight(self) -> None:
        checks = [
            {
                "check_id": "env_doctor",
                "status": "FAIL",
                "preopen_status_code": "ENV_DOCTOR_NOT_READY",
                "next_step": "corrigir env doctor",
            }
        ]
        actions = validator._build_next_actions(checks, preflight_ok=False)
        self.assertGreaterEqual(len(actions), 2)
        self.assertEqual(actions[0]["check_id"], "env_doctor")
        self.assertIn("set PROFIT_DLL_USER", actions[0]["command"])
        self.assertEqual(actions[-1]["check_id"], "final_recheck")

    def test_render_summary_mentions_failed_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.md"
            validator._render_summary(
                out,
                checks=[
                    {"check_id": "artifacts", "status": "FAIL", "details": "x", "next_step": "step A"},
                    {"check_id": "commands", "status": "PASS", "details": "ok", "next_step": "none"},
                ],
                preflight_ok=False,
                inputs={
                    "stress_manifest": "a",
                    "commands_file": "b",
                    "bundle_manifest": "c",
                    "readiness_manifest": "d",
                },
                preopen_status_code=validator.PREOPEN_STATUS_BLOCKED,
                next_actions=[
                    {
                        "priority": 1,
                        "check_id": "artifacts",
                        "status_code": "ARTIFACTS_REQUIRED_FILES_MISSING",
                        "action": "step A",
                        "command": "python scripts/run_overlay_ws_stress_regression.py",
                        "exit_criteria": "ok",
                    }
                ],
            )
            text = out.read_text(encoding="utf-8")
            self.assertIn("preflight_ok: `0`", text)
            self.assertIn("preopen_status_code: `PREOPEN_BLOCKED`", text)
            self.assertIn("`ARTIFACTS_REQUIRED_FILES_MISSING`", text)
            self.assertIn("artifacts: step A", text)
            self.assertIn("## Mensagens operacionais", text)
            self.assertIn("## Proximos passos operacionais", text)

    def test_manifest_roundtrip_ascii_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.manifest.json"
            payload = {"runner": "verify_cen05_preflight.py", "preflight_ok": False}
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            parsed = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(parsed["runner"], "verify_cen05_preflight.py")

    def test_check_readiness_passes_with_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "summary.manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            result = validator._check_readiness(
                manifest,
                {
                    "g8_ready": True,
                    "scenario_results": [
                        {
                            "scenario_id": "CEN-05",
                            "status": "PASS",
                            "classification": "CONFIRMED_READY",
                            "diagnosis": "ok",
                            "next_action": "seguir",
                            "diagnostics": {"field_issue_count": 0},
                        }
                    ],
                },
            )
            self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
