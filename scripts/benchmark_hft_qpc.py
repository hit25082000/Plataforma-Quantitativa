#!/usr/bin/env python3
"""
M7 benchmark: baseline vs CPU pinning using engine QPC diagnostics.

- Runs `engine.exe --run-seconds=<N>` for each profile (`baseline`/`pinned`)
- Captures stdout/stderr logs per run
- Parses QPC lines (`[HFT]` and `[SHM]`) and writes CSV + JSON manifest
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from runtime_env_bootstrap import bootstrap_runtime_env

HFT_LINE = re.compile(
    r"^\[HFT\] QPC (?P<metric>[a-zA-Z0-9_]+) ns: count=(?P<count>\d+) "
    r"p50=(?P<p50>\d+) p95=(?P<p95>\d+) p99=(?P<p99>\d+) "
    r"p999=(?P<p999>\d+) max=(?P<max>\d+) mean=(?P<mean>[0-9.]+)$"
)

SHM_LINE = re.compile(
    r"^\[SHM\] QPC write_trade duration ns: count=(?P<count>\d+) "
    r"p50=(?P<p50>\d+) p95=(?P<p95>\d+) p99=(?P<p99>\d+) "
    r"p999=(?P<p999>\d+) max=(?P<max>\d+) mean=(?P<mean>[0-9.]+)$"
)

SHM_LEGACY_LINE = re.compile(
    r"^\[SHM\] QPC write_trade duration ns: count=(?P<count>\d+) "
    r"p50=(?P<p50>\d+) p95=(?P<p95>\d+) p99=(?P<p99>\d+) mean=(?P<mean>[0-9.]+)$"
)


@dataclass
class MetricRow:
    run: str
    metric: str
    count: int
    p50_ns: int
    p95_ns: int
    p99_ns: int
    p999_ns: int
    max_ns: int
    mean_ns: float


@dataclass
class RunResult:
    run: str
    pinning: int
    exit_code: int
    elapsed_s: float
    stdout_log: str
    stderr_log: str
    metrics: List[MetricRow]


def parse_qpc_text(text: str, run_name: str) -> List[MetricRow]:
    rows: List[MetricRow] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m_hft = HFT_LINE.match(line)
        if m_hft:
            rows.append(
                MetricRow(
                    run=run_name,
                    metric=m_hft.group("metric"),
                    count=int(m_hft.group("count")),
                    p50_ns=int(m_hft.group("p50")),
                    p95_ns=int(m_hft.group("p95")),
                    p99_ns=int(m_hft.group("p99")),
                    p999_ns=int(m_hft.group("p999")),
                    max_ns=int(m_hft.group("max")),
                    mean_ns=float(m_hft.group("mean")),
                )
            )
            continue

        m_shm = SHM_LINE.match(line)
        if m_shm:
            rows.append(
                MetricRow(
                    run=run_name,
                    metric="shm_write_trade_duration",
                    count=int(m_shm.group("count")),
                    p50_ns=int(m_shm.group("p50")),
                    p95_ns=int(m_shm.group("p95")),
                    p99_ns=int(m_shm.group("p99")),
                    p999_ns=int(m_shm.group("p999")),
                    max_ns=int(m_shm.group("max")),
                    mean_ns=float(m_shm.group("mean")),
                )
            )
            continue

        m_shm_legacy = SHM_LEGACY_LINE.match(line)
        if m_shm_legacy:
            p99 = int(m_shm_legacy.group("p99"))
            rows.append(
                MetricRow(
                    run=run_name,
                    metric="shm_write_trade_duration",
                    count=int(m_shm_legacy.group("count")),
                    p50_ns=int(m_shm_legacy.group("p50")),
                    p95_ns=int(m_shm_legacy.group("p95")),
                    p99_ns=p99,
                    p999_ns=p99,
                    max_ns=p99,
                    mean_ns=float(m_shm_legacy.group("mean")),
                )
            )
    return rows


def parse_qpc_file(path: Path, run_name: str) -> List[MetricRow]:
    return parse_qpc_text(path.read_text(encoding="utf-8", errors="replace"), run_name)


def _run_env(run_name: str, args: argparse.Namespace, base_env: Dict[str, str]) -> Dict[str, str]:
    env = dict(base_env)
    env["HFT_QPC_DIAG"] = "1"
    env["HFT_QPC_SAMPLE_EVERY"] = str(args.hft_qpc_sample_every)
    env["HFT_QPC_MAX_SAMPLES"] = str(args.hft_qpc_max_samples)
    env["HFT_CORE_INDEX_MODE"] = str(args.hft_core_index_mode)
    env["HFT_PREFETCH"] = "1" if int(args.hft_prefetch) != 0 else "0"

    check_metric = str(getattr(args, "check_metric", "") or "").strip().lower()
    shm_metric_requested = check_metric.startswith("shm_")
    if args.enable_shm_qpc or shm_metric_requested:
        env["SHM_ENABLED"] = "1"
    if args.enable_shm_qpc:
        env["SHM_QPC_DIAG"] = "1"
        env["SHM_QPC_SAMPLE_EVERY"] = str(args.shm_qpc_sample_every)
        env["SHM_QPC_MAX_SAMPLES"] = str(args.shm_qpc_max_samples)
    env["SHM_LARGE_PAGES"] = "1" if bool(args.shm_large_pages) else "0"
    env["SHM_LARGE_PAGES_STRICT"] = "1" if bool(args.shm_large_pages_strict) else "0"
    env["SHM_NUMA_NODE"] = str(args.shm_numa_node)
    env["SHM_PREFETCH_NEXT_SLOT"] = "1" if int(args.shm_prefetch_next_slot) != 0 else "0"

    if run_name == "pinned":
        env["HFT_CPU_PINNING"] = "1"
        env["HFT_PROCESS_PRIORITY"] = "1"
        env["HFT_MAIN_CORE"] = str(args.main_core)
        env["HFT_PUBLISHER_CORE"] = str(args.publisher_core)
        env["HFT_PROFIT_CALLBACK_CORE"] = str(args.profit_callback_core)
    else:
        env["HFT_CPU_PINNING"] = "0"
        env["HFT_PROCESS_PRIORITY"] = "0"

    return env


def run_engine_profile(
    run_name: str,
    args: argparse.Namespace,
    run_dir: Path,
    base_env: Dict[str, str],
) -> RunResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / f"{run_name}.stdout.log"
    stderr_log = run_dir / f"{run_name}.stderr.log"

    cmd = [
        str(args.engine),
        f"--run-seconds={args.duration_seconds}",
    ]
    env = _run_env(run_name, args, base_env)

    t0 = time.perf_counter()
    timed_out = False
    with stdout_log.open("w", encoding="utf-8") as out, stderr_log.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            cmd,
            cwd=str(args.workdir),
            env=env,
            stdout=out,
            stderr=err,
            shell=False,
        )
        timeout = max(args.timeout_seconds, args.duration_seconds + 30.0)
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                exit_code = proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                exit_code = 1
    elapsed = time.perf_counter() - t0

    stderr_text = stderr_log.read_text(encoding="utf-8", errors="replace")
    if (
        timed_out
        and int(exit_code) != 0
        and "[Engine] run-seconds reached, starting graceful shutdown." in stderr_text
    ):
        exit_code = 0
    metrics = parse_qpc_text(stderr_text, run_name)
    return RunResult(
        run=run_name,
        pinning=1 if run_name == "pinned" else 0,
        exit_code=exit_code,
        elapsed_s=round(elapsed, 3),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        metrics=metrics,
    )


def _metric_index(run_results: Sequence[RunResult]) -> Dict[str, Dict[str, MetricRow]]:
    by_run: Dict[str, Dict[str, MetricRow]] = {}
    for result in run_results:
        metric_map = by_run.setdefault(result.run, {})
        for row in result.metrics:
            metric_map[row.metric] = row
    return by_run


def _infer_no_samples_reason(run_result: Optional[RunResult]) -> str:
    if run_result is None or len(run_result.metrics) != 0:
        return "metric_not_found"
    stderr_path = str(run_result.stderr_log or "").strip()
    if stderr_path:
        try:
            text = Path(stderr_path).read_text(encoding="utf-8", errors="replace").lower()
        except Exception:  # noqa: BLE001
            text = ""
        if "market connection timeout" in text or "[profit] market: 0" in text:
            return "market_not_connected"
        if "ret_ticker=-2147483647" in text:
            return "market_not_connected"
    return "no_qpc_samples"


def build_threshold_checks(run_results: Sequence[RunResult], args: argparse.Namespace) -> List[dict]:
    check_run = str(args.check_run).strip().lower()
    check_metric = str(args.check_metric).strip()
    target_p99 = int(args.target_p99_ns)
    target_p999 = int(args.target_p999_ns)

    check = {
        "run": check_run,
        "metric": check_metric,
        "target_p99_ns": target_p99,
        "target_p999_ns": target_p999,
        "actual_p99_ns": -1,
        "actual_p999_ns": -1,
        "status": "ok",
        "reason": "ok",
    }

    by_run = _metric_index(run_results)
    run_map = by_run.get(check_run)
    if run_map is None:
        check["status"] = "fail"
        check["reason"] = "run_not_found"
        return [check]
    run_result = next((item for item in run_results if str(item.run).strip().lower() == check_run), None)

    row = run_map.get(check_metric)
    if row is None:
        check["status"] = "fail"
        check["reason"] = _infer_no_samples_reason(run_result)
        return [check]

    check["actual_p99_ns"] = int(row.p99_ns)
    check["actual_p999_ns"] = int(row.p999_ns)
    if target_p99 >= 0 and row.p99_ns > target_p99:
        check["status"] = "fail"
        check["reason"] = "p99_above_target"
        return [check]
    if target_p999 >= 0 and row.p999_ns > target_p999:
        check["status"] = "fail"
        check["reason"] = "p999_above_target"
        return [check]
    if run_result is not None and int(run_result.exit_code) != 0:
        check["status"] = "fail"
        check["reason"] = f"run_exit_code_{int(run_result.exit_code)}"
        return [check]
    return [check]


def _has_failed_checks(checks: Sequence[dict]) -> bool:
    for item in checks:
        if str(item.get("status", "")).lower() != "ok":
            return True
    return False


def write_csv(path: Path, run_results: Sequence[RunResult], checks: Optional[Sequence[dict]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checks = checks or []
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "section",
                "run",
                "metric",
                "count",
                "p50_ns",
                "p95_ns",
                "p99_ns",
                "p999_ns",
                "max_ns",
                "mean_ns",
                "pinning",
                "exit_code",
                "elapsed_s",
                "stderr_log",
                "check_status",
                "check_reason",
                "target_p99_ns",
                "target_p999_ns",
            ]
        )

        for result in run_results:
            for row in result.metrics:
                w.writerow(
                    [
                        "SUMMARY",
                        result.run,
                        row.metric,
                        row.count,
                        row.p50_ns,
                        row.p95_ns,
                        row.p99_ns,
                        row.p999_ns,
                        row.max_ns,
                        f"{row.mean_ns:.2f}",
                        result.pinning,
                        result.exit_code,
                        f"{result.elapsed_s:.3f}",
                        result.stderr_log,
                        "",
                        "",
                        "",
                        "",
                    ]
                )

        by_run = _metric_index(run_results)
        if "baseline" in by_run and "pinned" in by_run:
            baseline = by_run["baseline"]
            pinned = by_run["pinned"]
            common_metrics = sorted(set(baseline.keys()).intersection(pinned.keys()))
            for metric in common_metrics:
                b = baseline[metric]
                p = pinned[metric]
                ratio = (b.p99_ns / p.p99_ns) if p.p99_ns > 0 else 0.0
                w.writerow(
                    [
                        "COMPARE",
                        "baseline_vs_pinned",
                        metric,
                        "",
                        "",
                        "",
                        f"{ratio:.4f}",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ]
                )

        for check in checks:
            w.writerow(
                [
                    "CHECK",
                    check["run"],
                    check["metric"],
                    "",
                    "",
                    "",
                    check["actual_p99_ns"],
                    check["actual_p999_ns"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    check["status"],
                    check["reason"],
                    check["target_p99_ns"],
                    check["target_p999_ns"],
                ]
            )


def write_manifest(
    path: Path,
    run_results: Sequence[RunResult],
    checks: Sequence[dict],
    args: argparse.Namespace,
    started: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at_epoch_s": started,
        "finished_at_epoch_s": time.time(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "args": {
            "engine": str(args.engine),
            "workdir": str(args.workdir),
            "duration_seconds": float(args.duration_seconds),
            "timeout_seconds": float(args.timeout_seconds),
            "runs": args.runs,
            "enable_shm_qpc": bool(args.enable_shm_qpc),
            "hft_qpc_sample_every": int(args.hft_qpc_sample_every),
            "hft_qpc_max_samples": int(args.hft_qpc_max_samples),
            "shm_qpc_sample_every": int(args.shm_qpc_sample_every),
            "shm_qpc_max_samples": int(args.shm_qpc_max_samples),
            "main_core": int(args.main_core),
            "publisher_core": int(args.publisher_core),
            "profit_callback_core": int(args.profit_callback_core),
            "hft_core_index_mode": str(args.hft_core_index_mode),
            "hft_prefetch": int(args.hft_prefetch),
            "shm_large_pages": bool(args.shm_large_pages),
            "shm_large_pages_strict": bool(args.shm_large_pages_strict),
            "shm_numa_node": int(args.shm_numa_node),
            "shm_prefetch_next_slot": int(args.shm_prefetch_next_slot),
            "check_run": str(args.check_run),
            "check_metric": str(args.check_metric),
            "target_p99_ns": int(args.target_p99_ns),
            "target_p999_ns": int(args.target_p999_ns),
            "fail_on_check": bool(args.fail_on_check),
        },
        "checks": [dict(item) for item in checks],
        "runs": [
            {
                **asdict(result),
                "metrics": [asdict(m) for m in result.metrics],
            }
            for result in run_results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_runs(raw: str) -> List[str]:
    runs = [x.strip().lower() for x in raw.split(",") if x.strip()]
    allowed = {"baseline", "pinned"}
    for run in runs:
        if run not in allowed:
            raise SystemExit(f"invalid run '{run}'. allowed: baseline,pinned")
    if not runs:
        raise SystemExit("--runs requires at least one run")
    return runs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, default=_ROOT / "engine" / "build" / "Release" / "engine.exe")
    ap.add_argument("--workdir", type=Path, default=_ROOT / "engine" / "build" / "Release")
    ap.add_argument("--duration-seconds", type=float, default=60.0)
    ap.add_argument("--timeout-seconds", type=float, default=180.0)
    ap.add_argument("--runs", type=str, default="baseline,pinned")
    ap.add_argument("--enable-shm-qpc", action="store_true", default=False)
    ap.add_argument("--hft-qpc-sample-every", type=int, default=1)
    ap.add_argument("--hft-qpc-max-samples", type=int, default=1_000_000)
    ap.add_argument("--shm-qpc-sample-every", type=int, default=1)
    ap.add_argument("--shm-qpc-max-samples", type=int, default=1_000_000)
    ap.add_argument("--main-core", type=int, default=0)
    ap.add_argument("--publisher-core", type=int, default=1)
    ap.add_argument("--profit-callback-core", type=int, default=2)
    ap.add_argument("--hft-core-index-mode", type=str, choices=["physical", "logical"], default="physical")
    ap.add_argument("--hft-prefetch", type=int, default=1)
    ap.add_argument("--shm-large-pages", action="store_true", default=False)
    ap.add_argument("--shm-large-pages-strict", action="store_true", default=False)
    ap.add_argument("--shm-numa-node", type=int, default=-1)
    ap.add_argument("--shm-prefetch-next-slot", type=int, default=1)
    ap.add_argument("--check-run", type=str, default="pinned")
    ap.add_argument("--check-metric", type=str, default="shm_write_trade_duration")
    ap.add_argument("--target-p99-ns", type=int, default=10_000)
    ap.add_argument("--target-p999-ns", type=int, default=20_000)
    ap.add_argument("--fail-on-check", action="store_true", default=False)
    ap.add_argument("--out", type=Path, default=_ROOT / "distributor" / "logs" / "hft_qpc_benchmark_last.csv")
    args = ap.parse_args()
    bootstrap_runtime_env(_ROOT)

    runs = _parse_runs(args.runs)
    if args.duration_seconds <= 0:
        raise SystemExit("--duration-seconds must be > 0")

    if not args.engine.exists():
        raise SystemExit(f"engine not found: {args.engine}")
    if not args.workdir.exists():
        raise SystemExit(f"workdir not found: {args.workdir}")

    logs_dir = args.out.parent / (args.out.stem + "_logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    base_env = dict(os.environ)
    started = time.time()
    results: List[RunResult] = []

    for run_name in runs:
        results.append(run_engine_profile(run_name, args, logs_dir, base_env))

    checks = build_threshold_checks(results, args)
    write_csv(args.out, results, checks)
    write_manifest(args.out.with_suffix(".manifest.json"), results, checks, args, started)

    print(f"Wrote: {args.out}")
    print(f"Wrote: {args.out.with_suffix('.manifest.json')}")
    if args.fail_on_check and _has_failed_checks(checks):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
