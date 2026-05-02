from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "run_overlay_ws_stress_regression.py"
    spec = importlib.util.spec_from_file_location("run_overlay_ws_stress_regression", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module()


class TestRunOverlayWsStressRegression(unittest.TestCase):
    def test_quantile_handles_edges(self) -> None:
        self.assertEqual(runner._quantile([], 0.95), 0.0)
        self.assertEqual(runner._quantile([7.0], 0.95), 7.0)
        self.assertAlmostEqual(runner._quantile([1.0, 3.0, 5.0], 0.5), 3.0)

    def test_run_scenario_backlog_stays_bounded(self) -> None:
        scenario = runner.Scenario(
            name="test_hf",
            duration_s=1.0,
            frame_hz=300.0,
            change_every_n=1,
            ws_publish_min_ms=100,
            send_cost_ms=1,
            client_count=2,
        )
        row = runner._run_scenario(scenario)
        self.assertEqual(row["queue_max"], 1)
        self.assertTrue(row["backlog_stable"])
        self.assertGreater(row["published_count"], 0)

    def test_write_artifacts_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            rows = [
                {
                    "scenario": "ok",
                    "duration_s": 1.0,
                    "frame_hz": 120.0,
                    "frames_produced": 120,
                    "frames_consumed": 120,
                    "queue_replaced": 80,
                    "queue_max": 1,
                    "published_count": 9,
                    "publish_rate_hz": 9.0,
                    "latency_p50_ms": 0.5,
                    "latency_p95_ms": 1.2,
                    "latency_p99_ms": 2.0,
                    "latency_max_ms": 3.0,
                    "latency_mean_ms": 0.7,
                    "backlog_stable": True,
                    "throttle_ms": 100,
                    "send_cost_ms": 2,
                    "client_count": 2,
                }
            ]
            csv_path = out_dir / "stress.csv"
            summary_path = out_dir / "summary.md"
            manifest_path = out_dir / "summary.manifest.json"

            runner.write_csv(csv_path, rows)
            gate = runner.evaluate(rows)
            runner.write_summary(summary_path, rows, overall_ok=bool(gate["ok"]))
            manifest = {"rows": rows, "gate": gate}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            self.assertTrue(gate["ok"])
            self.assertIn("scenario", csv_path.read_text(encoding="utf-8"))
            self.assertIn("overall_ok", summary_path.read_text(encoding="utf-8"))
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["rows"][0]["scenario"], "ok")


if __name__ == "__main__":
    unittest.main()
