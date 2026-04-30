"""Testes do benchmark IPC SHM/ZMQ."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_benchmark_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "benchmark_ipc_zmq_vs_shm.py"
    spec = importlib.util.spec_from_file_location("benchmark_ipc_zmq_vs_shm", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load benchmark module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_benchmark_module()


class TestBenchmarkEvidenceOutputs(unittest.TestCase):
    def test_manifest_and_csv_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "latency.csv"
            manifest = out.with_suffix(".manifest.json")

            shm_stats = bench.BenchStats("shm", [100, 200, 300])
            zmq_stats = bench.BenchStats("zmq", [400, 500, 600])
            bench.write_csv(out, shm_stats, zmq_stats)
            bench.write_manifest(
                manifest,
                {
                    "mode": "latency",
                    "result": {
                        "shm": shm_stats.summary(),
                        "zmq": zmq_stats.summary(),
                    },
                },
            )

            self.assertTrue(out.exists())
            self.assertTrue(manifest.exists())

            csv_text = out.read_text(encoding="utf-8")
            manifest_text = manifest.read_text(encoding="utf-8")

            self.assertIn("SUMMARY,shm,3,200,290,298", csv_text)
            self.assertIn("COMPARE,zmq_p50_over_shm_p50", csv_text)
            self.assertIn('"mode": "latency"', manifest_text)
            self.assertIn('"path": "shm"', manifest_text)
            self.assertIn('"path": "zmq"', manifest_text)

    def test_evaluate_stress_result(self) -> None:
        row = {
            "target_rate": 100_000,
            "ring_dropped_counter": 3,
            "crc_mismatch": 0,
            "payload_mismatch": 0,
            "achieved_rate_effective": 95_000.0,
        }
        ok = bench.evaluate_stress_result(
            row,
            max_dropped=3,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_achieved_rate=90_000.0,
            min_achieved_rate_ratio=0.90,
        )
        fail = bench.evaluate_stress_result(
            row,
            max_dropped=2,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_achieved_rate=90_000.0,
            min_achieved_rate_ratio=0.90,
        )
        fail_crc = bench.evaluate_stress_result(
            row | {"crc_mismatch": 1},
            max_dropped=3,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_achieved_rate=90_000.0,
            min_achieved_rate_ratio=0.90,
        )
        fail_rate = bench.evaluate_stress_result(
            row,
            max_dropped=3,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_achieved_rate=99_000.0,
            min_achieved_rate_ratio=0.99,
        )

        self.assertEqual(ok["stress_ok"], 1)
        self.assertEqual(fail["stress_ok"], 0)
        self.assertEqual(fail_crc["stress_ok"], 0)
        self.assertEqual(fail_rate["stress_ok"], 0)
        self.assertEqual(ok["max_ring_dropped_allowed"], 3)
        self.assertEqual(ok["max_crc_mismatch_allowed"], 0)
        self.assertEqual(ok["min_achieved_rate_allowed"], 90000.0)
        self.assertEqual(ok["min_achieved_rate_ratio_allowed"], 0.9)
        self.assertEqual(ok["achieved_rate_ratio"], 0.95)

    def test_evaluate_session_result(self) -> None:
        row = {
            "observed_trades": 10,
            "gap_messages": 2,
            "ring_dropped_counter": 99,
            "ring_dropped_delta": 0,
            "committed_mismatch": 1,
            "crc_mismatch": 0,
            "payload_mismatch": 0,
        }
        ok = bench.evaluate_session_result(
            row,
            max_gap_messages=2,
            max_ring_dropped=0,
            max_committed_mismatch=1,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_observed_trades=10,
        )
        fail = bench.evaluate_session_result(
            row,
            max_gap_messages=1,
            max_ring_dropped=0,
            max_committed_mismatch=1,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_observed_trades=10,
        )
        fail_payload = bench.evaluate_session_result(
            row | {"payload_mismatch": 1},
            max_gap_messages=2,
            max_ring_dropped=0,
            max_committed_mismatch=1,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_observed_trades=10,
        )
        fail_observed = bench.evaluate_session_result(
            row | {"observed_trades": 3},
            max_gap_messages=2,
            max_ring_dropped=0,
            max_committed_mismatch=1,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_observed_trades=10,
        )

        self.assertEqual(ok["session_ok"], 1)
        self.assertEqual(fail["session_ok"], 0)
        self.assertEqual(fail_payload["session_ok"], 0)
        self.assertEqual(fail_observed["session_ok"], 0)
        self.assertEqual(ok["max_gap_messages_allowed"], 2)
        self.assertEqual(ok["min_observed_trades_allowed"], 10)

    def test_evaluate_session_result_uses_ring_dropped_delta_when_present(self) -> None:
        row = {
            "observed_trades": 10,
            "gap_messages": 0,
            "ring_dropped_counter": 500,
            "ring_dropped_delta": 2,
            "committed_mismatch": 0,
            "crc_mismatch": 0,
            "payload_mismatch": 0,
        }
        fail = bench.evaluate_session_result(
            row,
            max_gap_messages=0,
            max_ring_dropped=1,
            max_committed_mismatch=0,
            max_crc_mismatch=0,
            max_payload_mismatch=0,
            min_observed_trades=1,
        )
        self.assertEqual(fail["session_ok"], 0)

    def test_write_kv_csv_uses_section_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stress_out = Path(tmp) / "stress.csv"
            session_out = Path(tmp) / "session.csv"

            bench.write_kv_csv(stress_out, "stress", {"foo": 1, "bar": 2})
            bench.write_kv_csv(session_out, "session", {"baz": 3})

            stress_text = stress_out.read_text(encoding="utf-8")
            session_text = session_out.read_text(encoding="utf-8")

            self.assertIn("STRESS,foo,1", stress_text)
            self.assertIn("STRESS,bar,2", stress_text)
            self.assertIn("SESSION,baz,3", session_text)


if __name__ == "__main__":
    unittest.main()
