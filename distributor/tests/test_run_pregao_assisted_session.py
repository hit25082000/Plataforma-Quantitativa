from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_pregao_assisted_session.py"
    spec = importlib.util.spec_from_file_location("run_pregao_assisted_session", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module()


class TestRunPregaoAssistedSession(unittest.TestCase):
    def test_duration_guard(self) -> None:
        with self.assertRaises(SystemExit):
            parser = runner.parse_args
            argv = sys.argv
            try:
                sys.argv = ["run_pregao_assisted_session.py", "--duration-sec", "20"]
                parser()
            finally:
                sys.argv = argv

    def test_dry_run_generates_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "evidence"
            argv = sys.argv
            try:
                sys.argv = [
                    "run_pregao_assisted_session.py",
                    "--out-dir",
                    str(out_dir),
                    "--duration-sec",
                    "60",
                    "--dry-run",
                ]
                exit_code = runner.main()
            finally:
                sys.argv = argv

            self.assertEqual(exit_code, 0)
            manifest = out_dir / "session.manifest.json"
            commands = out_dir / "commands.md"
            checklist = out_dir / "operator_checklist.md"
            self.assertTrue(manifest.exists())
            self.assertTrue(commands.exists())
            self.assertTrue(checklist.exists())

            parsed = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(parsed["dry_run"])
            self.assertEqual(parsed["operator_window_seconds"], 60)
            self.assertIn("scripts/run_ovr_stab_field_qa.py", commands.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
