from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
