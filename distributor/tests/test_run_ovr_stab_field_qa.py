from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_ovr_stab_field_qa.py"
    spec = importlib.util.spec_from_file_location("run_ovr_stab_field_qa", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module()


class TestRunOvrStabFieldQa(unittest.TestCase):
    def test_task_state_blocks_when_prerequisites_missing(self) -> None:
        probe = {
            "health_ok": False,
            "debug_ok": False,
            "status_ok": False,
            "trace_exists": False,
            "trace_path": "missing.jsonl",
        }
        row = runner._task_state(runner.QA_TASKS[0], probe, assume_manual_ready=False)
        self.assertEqual(row["state"], "blocked")
        self.assertGreaterEqual(len(row["blockers"]), 3)

    def test_task_state_ready_when_manual_and_env_available(self) -> None:
        probe = {
            "health_ok": True,
            "debug_ok": True,
            "status_ok": True,
            "trace_exists": True,
            "trace_path": "ok.jsonl",
        }
        task = runner.QA_TASKS[1]
        row = runner._task_state(task, probe, assume_manual_ready=True)
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["blockers"], [])

    def test_write_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            summary = out_dir / "summary.md"
            commands = out_dir / "commands.md"
            manifest = out_dir / "qa_session.manifest.json"
            probe = {
                "base_url": "http://127.0.0.1:8000",
                "health_ok": True,
                "debug_ok": True,
                "status_ok": True,
                "trace_exists": True,
                "trace_path": str(out_dir / "ocr_overlay_trace.jsonl"),
                "latest_evidence_dirs": [str(out_dir / "sample")],
            }
            tasks = [runner._task_state(task, probe, assume_manual_ready=True) for task in runner.QA_TASKS]
            runner._write_summary_md(summary, probe, tasks)
            runner._write_commands_md(commands, probe, out_dir)
            payload = {
                "probe": probe,
                "tasks": tasks,
                "artifacts": {
                    "summary_md": str(summary),
                    "commands_md": str(commands),
                    "qa_session_manifest": str(manifest),
                },
            }
            manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            self.assertIn("OVR-STAB-QA-02", summary.read_text(encoding="utf-8"))
            self.assertIn("collect_ocr_overlay_trace_60s.py", commands.read_text(encoding="utf-8"))
            parsed = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(parsed["tasks"]), 4)


if __name__ == "__main__":
    unittest.main()
