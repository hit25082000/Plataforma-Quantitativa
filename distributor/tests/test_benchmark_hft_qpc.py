"""Tests for HFT QPC benchmark tooling."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "benchmark_hft_qpc.py"
    spec = importlib.util.spec_from_file_location("benchmark_hft_qpc", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_module()


class TestBenchmarkHftQpc(unittest.TestCase):
    def test_parse_hft_and_shm_qpc_lines(self) -> None:
        text = "\n".join(
            [
                "[HFT] QPC profit_callback_interval ns: count=100 p50=1200 p95=2500 p99=3000 p999=3200 max=5500 mean=1800.25",
                "[SHM] QPC write_trade duration ns: count=80 p50=900 p95=1200 p99=1600 p999=1900 max=3000 mean=1100.5",
            ]
        )
        rows = bench.parse_qpc_text(text, "pinned")
        self.assertEqual(len(rows), 2)

        hft = rows[0]
        self.assertEqual(hft.run, "pinned")
        self.assertEqual(hft.metric, "profit_callback_interval")
        self.assertEqual(hft.p999_ns, 3200)
        self.assertEqual(hft.max_ns, 5500)

        shm = rows[1]
        self.assertEqual(shm.metric, "shm_write_trade_duration")
        self.assertEqual(shm.p99_ns, 1600)
        self.assertEqual(shm.p999_ns, 1900)

    def test_parse_legacy_shm_line(self) -> None:
        text = "[SHM] QPC write_trade duration ns: count=10 p50=100 p95=200 p99=300 mean=150.0"
        rows = bench.parse_qpc_text(text, "baseline")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.metric, "shm_write_trade_duration")
        self.assertEqual(row.p99_ns, 300)
        self.assertEqual(row.p999_ns, 300)
        self.assertEqual(row.max_ns, 300)

    def test_write_csv_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hft.csv"
            manifest = out.with_suffix(".manifest.json")

            baseline = bench.RunResult(
                run="baseline",
                pinning=0,
                exit_code=0,
                elapsed_s=2.0,
                stdout_log=str(Path(tmp) / "b.out.log"),
                stderr_log=str(Path(tmp) / "b.err.log"),
                metrics=[
                    bench.MetricRow(
                        run="baseline",
                        metric="profit_callback_interval",
                        count=10,
                        p50_ns=1000,
                        p95_ns=2000,
                        p99_ns=3000,
                        p999_ns=3500,
                        max_ns=4500,
                        mean_ns=1700.0,
                    )
                ],
            )
            pinned = bench.RunResult(
                run="pinned",
                pinning=1,
                exit_code=0,
                elapsed_s=2.1,
                stdout_log=str(Path(tmp) / "p.out.log"),
                stderr_log=str(Path(tmp) / "p.err.log"),
                metrics=[
                    bench.MetricRow(
                        run="pinned",
                        metric="profit_callback_interval",
                        count=10,
                        p50_ns=900,
                        p95_ns=1500,
                        p99_ns=2000,
                        p999_ns=2500,
                        max_ns=2800,
                        mean_ns=1300.0,
                    )
                ],
            )
            bench.write_csv(out, [baseline, pinned])
            bench.write_manifest(
                manifest,
                [baseline, pinned],
                checks=[
                    {
                        "run": "pinned",
                        "metric": "profit_callback_interval",
                        "target_p99_ns": 5000,
                        "target_p999_ns": 6000,
                        "actual_p99_ns": 2000,
                        "actual_p999_ns": 2500,
                        "status": "ok",
                        "reason": "ok",
                    }
                ],
                args=Namespace(
                    engine=Path("engine.exe"),
                    workdir=Path("."),
                    duration_seconds=10.0,
                    timeout_seconds=20.0,
                    runs="baseline,pinned",
                    enable_shm_qpc=True,
                    hft_qpc_sample_every=1,
                    hft_qpc_max_samples=1000,
                    shm_qpc_sample_every=1,
                    shm_qpc_max_samples=1000,
                    main_core=0,
                    publisher_core=1,
                    profit_callback_core=2,
                    hft_core_index_mode="physical",
                    hft_prefetch=1,
                    shm_large_pages=False,
                    shm_large_pages_strict=False,
                    shm_numa_node=-1,
                    shm_prefetch_next_slot=1,
                    check_run="pinned",
                    check_metric="profit_callback_interval",
                    target_p99_ns=5000,
                    target_p999_ns=6000,
                    fail_on_check=False,
                ),
                started=1_000.0,
            )

            csv_text = out.read_text(encoding="utf-8")
            self.assertIn("SUMMARY,baseline,profit_callback_interval,10,1000,2000,3000,3500,4500,1700.00,0,0,2.000", csv_text)
            self.assertIn("COMPARE,baseline_vs_pinned,profit_callback_interval", csv_text)

            manifest_obj = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest_obj["runs"]), 2)
            self.assertEqual(manifest_obj["runs"][0]["run"], "baseline")
            self.assertEqual(manifest_obj["runs"][1]["run"], "pinned")
            self.assertEqual(len(manifest_obj["checks"]), 1)
            self.assertEqual(manifest_obj["checks"][0]["status"], "ok")
            self.assertEqual(manifest_obj["args"]["hft_core_index_mode"], "physical")

    def test_build_threshold_checks(self) -> None:
        args = Namespace(
            check_run="pinned",
            check_metric="shm_write_trade_duration",
            target_p99_ns=1600,
            target_p999_ns=1900,
        )
        run = bench.RunResult(
            run="pinned",
            pinning=1,
            exit_code=0,
            elapsed_s=1.0,
            stdout_log="x",
            stderr_log="y",
            metrics=[
                bench.MetricRow(
                    run="pinned",
                    metric="shm_write_trade_duration",
                    count=10,
                    p50_ns=1000,
                    p95_ns=1300,
                    p99_ns=1600,
                    p999_ns=1900,
                    max_ns=2200,
                    mean_ns=1400.0,
                )
            ],
        )
        checks = bench.build_threshold_checks([run], args)
        self.assertEqual(checks[0]["status"], "ok")

        args.target_p99_ns = 1500
        checks_fail = bench.build_threshold_checks([run], args)
        self.assertEqual(checks_fail[0]["status"], "fail")
        self.assertEqual(checks_fail[0]["reason"], "p99_above_target")


if __name__ == "__main__":
    unittest.main()
