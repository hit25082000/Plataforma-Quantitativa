#!/usr/bin/env python3
"""
Orquestrador de evidência M6/M7.

- Executa matriz HFT (baseline/pinned com variações de Large Pages e NUMA)
- Executa sessão IPC SHM (diagnóstico de estabilidade/loss)
- Consolida resultados em summary.csv + summary.manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from runtime_env_bootstrap import bootstrap_runtime_env


def parse_int_list(raw: str, name: str) -> List[int]:
    if raw is None or not str(raw).strip():
        raise ValueError(f"{name} cannot be empty")
    out: List[int] = []
    for token in str(raw).split(","):
        item = token.strip()
        if not item:
            continue
        out.append(int(item))
    if not out:
        raise ValueError(f"{name} must contain at least one integer")
    return out


def parse_token_list(raw: str, name: str) -> List[str]:
    if raw is None or not str(raw).strip():
        raise ValueError(f"{name} cannot be empty")
    out = [token.strip() for token in str(raw).split(",") if token.strip()]
    if not out:
        raise ValueError(f"{name} must contain at least one value")
    return out


def parse_binary_list(raw: str, name: str) -> List[int]:
    values = parse_int_list(raw, name)
    for value in values:
        if value not in (0, 1):
            raise ValueError(f"{name} accepts only 0 or 1 values")
    return values


def parse_positive_int(raw: str, name: str) -> int:
    value = int(str(raw).strip())
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def parse_positive_float(raw: str, name: str) -> float:
    value = float(str(raw).strip())
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def parse_non_negative_int(raw: str, name: str) -> int:
    value = int(str(raw).strip())
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def parse_optional_non_negative_int(raw: str, name: str) -> int:
    value = int(str(raw).strip())
    if value == -1:
        return value
    if value < 0:
        raise ValueError(f"{name} must be >= 0 or -1")
    return value


def resolve_window_seconds(
    *,
    total_seconds: float,
    window_seconds: float,
    windows: int,
) -> float:
    if total_seconds > 0:
        return float(total_seconds) / float(windows)
    return float(window_seconds)


def resolve_hft_window_seconds(
    *,
    total_seconds: float,
    window_seconds: float,
    windows: int,
    scenario_count: int,
    run_count: int,
) -> float:
    if total_seconds > 0:
        slot_count = max(1, int(windows)) * max(1, int(scenario_count)) * max(1, int(run_count))
        return float(total_seconds) / float(slot_count)
    return float(window_seconds)


def _load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_resume_manifest_valid(csv_path: Path, manifest: Dict) -> bool:
    if not manifest:
        return False

    stem = csv_path.stem.lower()
    if stem == "session":
        mode = str(manifest.get("mode", "")).strip().lower()
        result = manifest.get("result")
        return bool(mode == "session" and isinstance(result, dict) and "session_ok" in result)

    if stem == "summary":
        checks = manifest.get("checks")
        return bool(isinstance(checks, list) and len(checks) > 0)

    return True


def _resume_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return bool(actual) == bool(expected)

    actual_is_number = isinstance(actual, (int, float)) and not isinstance(actual, bool)
    expected_is_number = isinstance(expected, (int, float)) and not isinstance(expected, bool)
    if actual_is_number and expected_is_number:
        return float(actual) == float(expected)

    if isinstance(actual, (list, dict)) or isinstance(expected, (list, dict)):
        try:
            left = json.dumps(actual, sort_keys=True, ensure_ascii=False)
            right = json.dumps(expected, sort_keys=True, ensure_ascii=False)
            return left == right
        except Exception:  # noqa: BLE001
            return False

    return str(actual) == str(expected)


def _resume_args_match(manifest: Dict, expected_args: Optional[Dict[str, Any]]) -> bool:
    if not expected_args:
        return True
    manifest_args = manifest.get("args")
    if not isinstance(manifest_args, dict):
        return False
    for key, expected_value in expected_args.items():
        if key not in manifest_args:
            return False
        if not _resume_value_matches(manifest_args.get(key), expected_value):
            return False
    return True


def _can_resume_artifact(csv_path: Path, manifest_path: Path, expected_args: Optional[Dict[str, Any]] = None) -> bool:
    if not csv_path.exists() or not manifest_path.exists():
        return False
    if csv_path.stat().st_size <= 0 or manifest_path.stat().st_size <= 0:
        return False
    try:
        csv_lines = [line for line in csv_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:  # noqa: BLE001
        return False
    if len(csv_lines) < 2:
        return False

    manifest = _load_json(manifest_path)
    if not _is_resume_manifest_valid(csv_path, manifest):
        return False
    return _resume_args_match(manifest, expected_args)


def _should_reuse_existing_result(
    *,
    resume_requested: bool,
    artifact_valid: bool,
    eval_ok: bool,
    resume_allow_failed: bool,
) -> bool:
    if not resume_requested or not artifact_valid:
        return False
    if bool(eval_ok):
        return True
    return bool(resume_allow_failed)


def _build_hft_resume_expected_args(
    args: argparse.Namespace,
    *,
    hft_benchmark_duration_seconds: float,
    hft_runs: List[str],
    lp: int,
    numa: int,
) -> Dict[str, Any]:
    return {
        "engine": str(args.engine),
        "workdir": str(args.workdir),
        "duration_seconds": float(hft_benchmark_duration_seconds),
        "runs": ",".join(hft_runs),
        "enable_shm_qpc": bool(args.hft_enable_shm_qpc),
        "hft_qpc_sample_every": int(args.hft_qpc_sample_every),
        "hft_qpc_max_samples": int(args.hft_qpc_max_samples),
        "shm_qpc_sample_every": int(args.shm_qpc_sample_every),
        "shm_qpc_max_samples": int(args.shm_qpc_max_samples),
        "main_core": int(args.hft_main_core),
        "publisher_core": int(args.hft_publisher_core),
        "profit_callback_core": int(args.hft_profit_callback_core),
        "hft_core_index_mode": str(args.hft_core_index_mode),
        "hft_prefetch": int(args.hft_prefetch),
        "shm_large_pages": bool(lp == 1),
        "shm_large_pages_strict": bool(args.hft_shm_large_pages_strict),
        "shm_numa_node": int(numa),
        "shm_prefetch_next_slot": int(args.hft_shm_prefetch_next_slot),
        "check_run": str(args.hft_check_run),
        "check_metric": str(args.hft_check_metric),
        "target_p99_ns": int(args.hft_target_p99_ns),
        "target_p999_ns": int(args.hft_target_p999_ns),
        "fail_on_check": bool(args.hft_fail_on_check),
    }


def _build_ipc_resume_expected_args(
    args: argparse.Namespace,
    *,
    session_window_seconds: float,
) -> Dict[str, Any]:
    return {
        "stress": False,
        "session": True,
        "session_seconds": float(session_window_seconds),
        "session_max_gap_messages": int(args.session_max_gap_messages),
        "session_max_ring_dropped": int(args.session_max_ring_dropped),
        "session_max_committed_mismatch": int(args.session_max_committed_mismatch),
        "session_max_crc_mismatch": int(args.session_max_crc_mismatch),
        "session_max_payload_mismatch": int(args.session_max_payload_mismatch),
        "session_min_observed_trades": int(args.session_min_observed_trades),
        "session_fail_on_loss": bool(args.session_fail_on_loss),
        "shm_name": str(args.session_shm_name),
        "shm_mb": int(args.session_shm_mb),
    }


def _mapping_candidates(mapping_name: str) -> List[str]:
    raw = (mapping_name or "").strip()
    if not raw:
        return [raw]
    candidates = [raw]
    if "\\" in raw:
        normalized = raw.split("\\", 1)[1]
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _probe_session_mapping(mapping_name: str) -> Dict[str, Any]:
    try:
        from multiprocessing import shared_memory
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "candidate": "",
            "reason": f"shared_memory_unavailable:{type(exc).__name__}",
        }

    last_reason = "mapping_not_found"
    for candidate in _mapping_candidates(mapping_name):
        try:
            shm = shared_memory.SharedMemory(name=candidate, create=False)
        except FileNotFoundError:
            last_reason = "mapping_not_found"
            continue
        except OSError as exc:
            last_reason = f"mapping_open_failed:{exc}"
            continue
        except Exception as exc:  # noqa: BLE001
            last_reason = f"mapping_open_failed:{type(exc).__name__}:{exc}"
            continue
        try:
            return {"ok": True, "candidate": candidate, "reason": "ok"}
        finally:
            shm.close()
    return {"ok": False, "candidate": "", "reason": last_reason}


def _wait_for_session_mapping(mapping_name: str, timeout_seconds: float, poll_interval_seconds: float = 0.5) -> Dict[str, Any]:
    deadline = time.time() + max(0.1, float(timeout_seconds))
    probe = _probe_session_mapping(mapping_name)
    while time.time() < deadline:
        if bool(probe.get("ok", False)):
            return probe
        time.sleep(max(0.05, float(poll_interval_seconds)))
        probe = _probe_session_mapping(mapping_name)
    return probe


def _start_ipc_engine_producer(
    *,
    args: argparse.Namespace,
    ipc_dir: Path,
    session_window_seconds: float,
) -> Dict[str, Any]:
    producer_stdout_path = ipc_dir / "producer.stdout.log"
    producer_stderr_path = ipc_dir / "producer.stderr.log"
    producer_stdout_f = producer_stdout_path.open("w", encoding="utf-8")
    producer_stderr_f = producer_stderr_path.open("w", encoding="utf-8")

    run_seconds = max(30.0, float(session_window_seconds) + float(args.session_producer_lead_seconds))
    cmd = [str(args.engine), f"--run-seconds={run_seconds}"]
    env = dict(os.environ)
    env["SHM_ENABLED"] = "1"
    env["SHM_MAPPING_NAME"] = str(args.session_shm_name)
    env["SHM_SIZE_MB"] = str(int(args.session_shm_mb))
    ticker = str(args.session_producer_ticker).strip()
    bolsa = str(args.session_producer_bolsa).strip()
    if ticker:
        env["PROFIT_TICKER"] = ticker
    if bolsa:
        env["PROFIT_BOLSA"] = bolsa

    proc = subprocess.Popen(
        cmd,
        cwd=str(args.workdir),
        env=env,
        stdout=producer_stdout_f,
        stderr=producer_stderr_f,
        shell=False,
    )
    return {
        "process": proc,
        "stdout_handle": producer_stdout_f,
        "stderr_handle": producer_stderr_f,
        "stdout_log": str(producer_stdout_path),
        "stderr_log": str(producer_stderr_path),
        "run_seconds": run_seconds,
    }


def _stop_background_process(proc: subprocess.Popen, timeout_seconds: float = 10.0) -> int:
    if proc.poll() is not None:
        return int(proc.returncode)
    try:
        proc.terminate()
        proc.wait(timeout=max(1.0, float(timeout_seconds)))
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
            proc.wait(timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
    return int(proc.returncode) if proc.returncode is not None else -1


def _producer_log_indicates_market_not_connected(stderr_log_path: str) -> bool:
    path = str(stderr_log_path or "").strip()
    if not path:
        return False
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").lower()
    except Exception:  # noqa: BLE001
        return False

    markers = (
        "market connection timeout",
        "ret_ticker=-2147483647",
        "[profit] market: 0",
        "subscribe may fail",
    )
    return any(marker in text for marker in markers)


def run_command(
    cmd: List[str],
    cwd: Path,
    stdout_log: Path,
    stderr_log: Path,
) -> Dict:
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with stdout_log.open("w", encoding="utf-8") as out_f, stderr_log.open("w", encoding="utf-8") as err_f:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=out_f,
            stderr=err_f,
            shell=False,
            check=False,
        )
    elapsed = time.time() - started
    return {
        "exit_code": int(proc.returncode),
        "elapsed_s": round(elapsed, 3),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }


def evaluate_hft_manifest(
    manifest: Dict,
    exit_code: int,
    check_run: str,
    check_metric: str,
) -> Dict:
    checks = list(manifest.get("checks") or [])
    selected: Optional[Dict] = None
    for item in checks:
        if str(item.get("run", "")).strip().lower() == str(check_run).strip().lower() and str(
            item.get("metric", "")
        ).strip() == str(check_metric).strip():
            selected = item
            break
    if selected is None and checks:
        selected = checks[0]

    if selected is None:
        status_ok = exit_code == 0
        check_reason = "no_check_recorded"
        actual_p99 = -1
        actual_p999 = -1
        target_p99 = -1
        target_p999 = -1
    else:
        status_ok = str(selected.get("status", "")).lower() == "ok"
        check_reason = str(selected.get("reason", "ok" if status_ok else "check_failed"))
        actual_p99 = int(selected.get("actual_p99_ns", -1))
        actual_p999 = int(selected.get("actual_p999_ns", -1))
        target_p99 = int(selected.get("target_p99_ns", -1))
        target_p999 = int(selected.get("target_p999_ns", -1))

    if bool(status_ok):
        if exit_code != 0:
            ok = False
            reason = f"exit_code_{exit_code}"
        else:
            ok = True
            reason = "ok"
    else:
        ok = False
        reason = check_reason

    return {
        "ok": ok,
        "reason": reason,
        "check_run": str(check_run),
        "check_metric": str(check_metric),
        "actual_p99_ns": actual_p99,
        "actual_p999_ns": actual_p999,
        "target_p99_ns": target_p99,
        "target_p999_ns": target_p999,
    }


def aggregate_hft_results(hft_rows: List[Dict]) -> List[Dict]:
    if not hft_rows:
        return []

    grouped: Dict[str, List[Dict]] = {}
    for row in hft_rows:
        scenario = str(row.get("scenario", "")).strip() or "unknown"
        grouped.setdefault(scenario, []).append(row)

    aggregates: List[Dict] = []
    for scenario in sorted(grouped.keys()):
        rows = grouped[scenario]
        failed_rows = [row for row in rows if not bool(row.get("ok", False))]
        first = rows[0]
        exit_code = next((int(row.get("exit_code", 0)) for row in rows if int(row.get("exit_code", 0)) != 0), 0)

        def _max_or_unknown(key: str) -> int:
            values = [int(row.get(key, -1)) for row in rows]
            if not values or any(value < 0 for value in values):
                return -1
            return int(max(values))

        aggregates.append(
            {
                "scenario": scenario,
                "ok": bool(all(bool(row.get("ok", False)) for row in rows)),
                "reason": "ok" if not failed_rows else str(failed_rows[0].get("reason", "check_failed")),
                "exit_code": exit_code,
                "elapsed_s": float(sum(float(row.get("elapsed_s", 0.0)) for row in rows)),
                "window_count": int(len(rows)),
                "failed_windows": int(len(failed_rows)),
                "max_actual_p99_ns": _max_or_unknown("actual_p99_ns"),
                "max_actual_p999_ns": _max_or_unknown("actual_p999_ns"),
                "target_p99_ns": int(first.get("target_p99_ns", -1)),
                "target_p999_ns": int(first.get("target_p999_ns", -1)),
                "check_run": str(first.get("check_run", "")),
                "check_metric": str(first.get("check_metric", "")),
                "skipped_existing_windows": int(sum(1 for row in rows if bool(row.get("skipped_existing", False)))),
                "artifact_csv": str(first.get("artifact_csv", "")),
                "artifact_manifest": str(first.get("artifact_manifest", "")),
                "stdout_log": str(first.get("stdout_log", "")),
                "stderr_log": str(first.get("stderr_log", "")),
            }
        )
    return aggregates


def evaluate_hft_aggregate_gates(
    hft_aggregate_rows: List[Dict],
    *,
    max_failed_windows: int,
    max_p99_ns: int,
    max_p999_ns: int,
) -> Dict:
    limits = {
        "max_failed_windows": int(max_failed_windows),
        "max_p99_ns": int(max_p99_ns),
        "max_p999_ns": int(max_p999_ns),
    }
    enabled = any(value >= 0 for value in limits.values())
    if not enabled:
        return {
            "enabled": False,
            "ok": True,
            "reason": "disabled",
            "failed_gate": "",
            "failed_scenario": "",
            **limits,
        }
    if not hft_aggregate_rows:
        return {
            "enabled": True,
            "ok": False,
            "reason": "no_hft_aggregate_rows",
            "failed_gate": "no_hft_aggregate_rows",
            "failed_scenario": "",
            **limits,
        }

    for row in hft_aggregate_rows:
        scenario = str(row.get("scenario", ""))
        checks = [
            ("max_failed_windows", int(row.get("failed_windows", -1)), lambda actual, limit: actual <= limit),
            ("max_p99_ns", int(row.get("max_actual_p99_ns", -1)), lambda actual, limit: actual <= limit),
            ("max_p999_ns", int(row.get("max_actual_p999_ns", -1)), lambda actual, limit: actual <= limit),
        ]
        for gate_name, actual, gate_check in checks:
            gate_limit = int(limits[gate_name])
            if gate_limit < 0:
                continue
            if actual < 0:
                return {
                    "enabled": True,
                    "ok": False,
                    "reason": f"{gate_name}_unknown",
                    "failed_gate": gate_name,
                    "failed_scenario": scenario,
                    **limits,
                }
            if not gate_check(actual, gate_limit):
                return {
                    "enabled": True,
                    "ok": False,
                    "reason": f"{gate_name}_failed",
                    "failed_gate": gate_name,
                    "failed_scenario": scenario,
                    **limits,
                }

    return {
        "enabled": True,
        "ok": True,
        "reason": "ok",
        "failed_gate": "",
        "failed_scenario": "",
        **limits,
    }


def is_non_fatal_failure_reason(reason: Any) -> bool:
    normalized = str(reason or "").strip().lower()
    return normalized in {"market_not_connected"}


def should_fail_on_any(
    hft_rows: List[Dict],
    ipc_rows: List[Dict],
    hft_aggregate_gate: Dict,
    ipc_aggregate_gate: Dict,
) -> bool:
    for row in hft_rows:
        if bool(row.get("ok", False)):
            continue
        if is_non_fatal_failure_reason(row.get("reason", "")):
            continue
        return True

    for row in ipc_rows:
        if bool(row.get("ok", False)):
            continue
        if is_non_fatal_failure_reason(row.get("reason", "")):
            continue
        return True

    if bool(hft_aggregate_gate.get("enabled", False)) and not bool(hft_aggregate_gate.get("ok", False)):
        return True

    if bool(ipc_aggregate_gate.get("enabled", False)) and not bool(ipc_aggregate_gate.get("ok", False)):
        return True

    return False


def evaluate_ipc_session_manifest(manifest: Dict, exit_code: int) -> Dict:
    result = dict(manifest.get("result") or {})
    session_ok = int(result.get("session_ok", 0))
    session_error = str(result.get("session_error", "") or "")
    observed_trades = int(result.get("observed_trades", 0))
    write_seq_delta = int(result.get("write_seq_delta", 0))
    min_observed = int(result.get("min_observed_trades_allowed", -1))
    mode = str(manifest.get("mode", "")).strip().lower()
    mode_ok = mode == "session"
    ok = bool(exit_code == 0 and mode_ok and session_ok == 1)
    reason = "ok"
    if not mode_ok:
        reason = "mode_not_session"
    elif session_ok != 1:
        if "filenotfounderror" in session_error.lower():
            reason = "session_mapping_not_found"
        elif write_seq_delta <= 0 and observed_trades <= 0 and min_observed > 0:
            reason = "session_no_shm_writes"
        elif observed_trades < max(0, min_observed):
            reason = "session_observed_below_min"
        else:
            reason = "session_gate_failed"
    elif exit_code != 0:
        reason = f"exit_code_{exit_code}"
    return {
        "ok": ok,
        "reason": reason,
        "gap_messages": int(result.get("gap_messages", -1)),
        "ring_dropped_delta": int(result.get("ring_dropped_delta", result.get("ring_dropped_counter", -1))),
        "committed_mismatch": int(result.get("committed_mismatch", -1)),
        "crc_mismatch": int(result.get("crc_mismatch", -1)),
        "payload_mismatch": int(result.get("payload_mismatch", -1)),
        "observed_trades": int(result.get("observed_trades", -1)),
        "session_ok": session_ok,
        "max_gap_messages_allowed": int(result.get("max_gap_messages_allowed", -1)),
        "max_ring_dropped_allowed": int(result.get("max_ring_dropped_allowed", -1)),
        "max_committed_mismatch_allowed": int(result.get("max_committed_mismatch_allowed", -1)),
        "max_crc_mismatch_allowed": int(result.get("max_crc_mismatch_allowed", -1)),
        "max_payload_mismatch_allowed": int(result.get("max_payload_mismatch_allowed", -1)),
        "min_observed_trades_allowed": int(result.get("min_observed_trades_allowed", -1)),
        "session_error": session_error,
    }


def aggregate_ipc_results(ipc_rows: List[Dict]) -> Dict:
    if not ipc_rows:
        return {
            "scenario": "session",
            "ok": False,
            "reason": "no_ipc_windows",
            "exit_code": -1,
            "elapsed_s": 0.0,
            "window_count": 0,
            "gap_messages": -1,
            "ring_dropped_delta": -1,
            "committed_mismatch": -1,
            "crc_mismatch": -1,
            "payload_mismatch": -1,
            "observed_trades": -1,
            "session_ok": 0,
            "max_gap_messages_allowed": -1,
            "max_ring_dropped_allowed": -1,
            "max_committed_mismatch_allowed": -1,
            "max_crc_mismatch_allowed": -1,
            "max_payload_mismatch_allowed": -1,
            "min_observed_trades_allowed": -1,
            "skipped_existing_windows": 0,
            "artifact_csv": "",
            "artifact_manifest": "",
            "stdout_log": "",
            "stderr_log": "",
        }

    def _sum_or_unknown(key: str) -> int:
        values = [int(row.get(key, -1)) for row in ipc_rows]
        if any(value < 0 for value in values):
            return -1
        return int(sum(values))

    first = ipc_rows[0]
    not_ok = next((row for row in ipc_rows if not bool(row.get("ok"))), None)
    exit_code = next((int(row.get("exit_code", 0)) for row in ipc_rows if int(row.get("exit_code", 0)) != 0), 0)
    return {
        "scenario": "session",
        "ok": bool(all(bool(row.get("ok")) for row in ipc_rows)),
        "reason": "ok" if not not_ok else str(not_ok.get("reason", "session_gate_failed")),
        "exit_code": exit_code,
        "elapsed_s": float(sum(float(row.get("elapsed_s", 0.0)) for row in ipc_rows)),
        "window_count": int(len(ipc_rows)),
        "gap_messages": _sum_or_unknown("gap_messages"),
        "ring_dropped_delta": _sum_or_unknown("ring_dropped_delta"),
        "committed_mismatch": _sum_or_unknown("committed_mismatch"),
        "crc_mismatch": _sum_or_unknown("crc_mismatch"),
        "payload_mismatch": _sum_or_unknown("payload_mismatch"),
        "observed_trades": _sum_or_unknown("observed_trades"),
        "session_ok": 1 if all(int(row.get("session_ok", 0)) == 1 for row in ipc_rows) else 0,
        "max_gap_messages_allowed": int(first.get("max_gap_messages_allowed", -1)),
        "max_ring_dropped_allowed": int(first.get("max_ring_dropped_allowed", -1)),
        "max_committed_mismatch_allowed": int(first.get("max_committed_mismatch_allowed", -1)),
        "max_crc_mismatch_allowed": int(first.get("max_crc_mismatch_allowed", -1)),
        "max_payload_mismatch_allowed": int(first.get("max_payload_mismatch_allowed", -1)),
        "min_observed_trades_allowed": int(first.get("min_observed_trades_allowed", -1)),
        "skipped_existing_windows": int(sum(1 for row in ipc_rows if bool(row.get("skipped_existing", False)))),
        "artifact_csv": str(first.get("artifact_csv", "")),
        "artifact_manifest": str(first.get("artifact_manifest", "")),
        "stdout_log": str(first.get("stdout_log", "")),
        "stderr_log": str(first.get("stderr_log", "")),
    }


def evaluate_ipc_aggregate_gates(
    ipc_result: Dict,
    *,
    max_gap_messages: int,
    max_ring_dropped: int,
    max_committed_mismatch: int,
    max_crc_mismatch: int,
    max_payload_mismatch: int,
    min_observed_trades: int,
) -> Dict:
    limits = {
        "max_gap_messages": int(max_gap_messages),
        "max_ring_dropped": int(max_ring_dropped),
        "max_committed_mismatch": int(max_committed_mismatch),
        "max_crc_mismatch": int(max_crc_mismatch),
        "max_payload_mismatch": int(max_payload_mismatch),
        "min_observed_trades": int(min_observed_trades),
    }

    enabled = any(value >= 0 for value in limits.values())
    if not enabled:
        return {
            "enabled": False,
            "ok": True,
            "reason": "disabled",
            "failed_gate": "",
            **limits,
        }

    checks = [
        ("max_gap_messages", int(ipc_result.get("gap_messages", -1)), lambda actual, limit: actual <= limit),
        ("max_ring_dropped", int(ipc_result.get("ring_dropped_delta", -1)), lambda actual, limit: actual <= limit),
        (
            "max_committed_mismatch",
            int(ipc_result.get("committed_mismatch", -1)),
            lambda actual, limit: actual <= limit,
        ),
        ("max_crc_mismatch", int(ipc_result.get("crc_mismatch", -1)), lambda actual, limit: actual <= limit),
        (
            "max_payload_mismatch",
            int(ipc_result.get("payload_mismatch", -1)),
            lambda actual, limit: actual <= limit,
        ),
        (
            "min_observed_trades",
            int(ipc_result.get("observed_trades", -1)),
            lambda actual, limit: actual >= limit,
        ),
    ]

    for gate_name, actual, gate_check in checks:
        gate_limit = int(limits[gate_name])
        if gate_limit < 0:
            continue
        if actual < 0:
            return {
                "enabled": True,
                "ok": False,
                "reason": f"{gate_name}_unknown",
                "failed_gate": gate_name,
                **limits,
            }
        if not gate_check(actual, gate_limit):
            return {
                "enabled": True,
                "ok": False,
                "reason": f"{gate_name}_failed",
                "failed_gate": gate_name,
                **limits,
            }

    return {
        "enabled": True,
        "ok": True,
        "reason": "ok",
        "failed_gate": "",
        **limits,
    }


def execute_with_retries(
    *,
    run_once: Callable[[], Dict],
    is_ok: Callable[[Dict], bool],
    max_retries: int,
    retry_delay_seconds: float,
) -> Dict:
    retries = max(0, int(max_retries))
    attempt = 1
    latest: Dict = {}
    while attempt <= retries + 1:
        latest = dict(run_once())
        latest["attempt"] = attempt
        if is_ok(latest):
            break
        if attempt > retries:
            break
        if retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)
        attempt += 1
    latest["attempts"] = int(latest.get("attempt", attempt))
    latest["retried"] = bool(int(latest["attempts"]) > 1)
    return latest


def write_summary_csv(
    path: Path,
    hft_rows: List[Dict],
    ipc_rows: List[Dict],
    ipc_aggregate_row: Dict,
    overall_ok: bool,
    hft_aggregate_rows: Optional[List[Dict]] = None,
    hft_aggregate_gate: Optional[Dict] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hft_aggregate_rows = list(hft_aggregate_rows or [])
    hft_aggregate_gate = dict(hft_aggregate_gate or {})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = [
            "section",
            "scenario",
            "window_index",
            "skipped_existing",
            "attempts",
            "retried",
            "ok",
            "exit_code",
            "reason",
            "check_run",
            "check_metric",
            "actual_p99_ns",
            "actual_p999_ns",
            "target_p99_ns",
            "target_p999_ns",
            "gap_messages",
            "ring_dropped_delta",
            "committed_mismatch",
            "crc_mismatch",
            "payload_mismatch",
            "observed_trades",
            "artifact_csv",
            "artifact_manifest",
        ]
        w.writerow(header)

        def _emit(row: List[object]) -> None:
            if len(row) != len(header):
                raise ValueError(f"summary.csv row has {len(row)} columns, expected {len(header)}")
            w.writerow(row)

        for row in hft_rows:
            _emit(
                [
                    "HFT",
                    row["scenario"],
                    row.get("window_index", 1),
                    int(bool(row.get("skipped_existing", False))),
                    int(row.get("attempts", 1)),
                    int(bool(row.get("retried", False))),
                    int(bool(row["ok"])),
                    row["exit_code"],
                    row["reason"],
                    row["check_run"],
                    row["check_metric"],
                    row["actual_p99_ns"],
                    row["actual_p999_ns"],
                    row["target_p99_ns"],
                    row["target_p999_ns"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    row["artifact_csv"],
                    row["artifact_manifest"],
                ]
            )

        for row in hft_aggregate_rows:
            _emit(
                [
                    "HFT_AGGREGATE",
                    row.get("scenario", ""),
                    "",
                    int(row.get("skipped_existing_windows", 0)),
                    "",
                    "",
                    int(bool(row.get("ok", False))),
                    row.get("exit_code", ""),
                    row.get("reason", ""),
                    row.get("check_run", ""),
                    row.get("check_metric", ""),
                    row.get("max_actual_p99_ns", ""),
                    row.get("max_actual_p999_ns", ""),
                    row.get("target_p99_ns", ""),
                    row.get("target_p999_ns", ""),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    row.get("artifact_csv", ""),
                    row.get("artifact_manifest", ""),
                ]
            )

        _emit(
            [
                "HFT_AGGREGATE_GATE",
                "all",
                "",
                "",
                "",
                "",
                int(bool(hft_aggregate_gate.get("ok", True))),
                "",
                hft_aggregate_gate.get("reason", ""),
                hft_aggregate_gate.get("failed_scenario", ""),
                hft_aggregate_gate.get("failed_gate", ""),
                "",
                "",
                hft_aggregate_gate.get("max_p99_ns", ""),
                hft_aggregate_gate.get("max_p999_ns", ""),
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

        for row in ipc_rows:
            _emit(
                [
                    "IPC_SESSION",
                    row["scenario"],
                    row.get("window_index", ""),
                    int(bool(row.get("skipped_existing", False))),
                    int(row.get("attempts", 1)),
                    int(bool(row.get("retried", False))),
                    int(bool(row["ok"])),
                    row["exit_code"],
                    row["reason"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    row["gap_messages"],
                    row["ring_dropped_delta"],
                    row["committed_mismatch"],
                    row["crc_mismatch"],
                    row["payload_mismatch"],
                    row["observed_trades"],
                    row["artifact_csv"],
                    row["artifact_manifest"],
                ]
            )

        _emit(
            [
                "IPC_AGGREGATE",
                "session",
                "",
                "",
                "",
                "",
                int(bool(ipc_aggregate_row.get("ok", True))),
                ipc_aggregate_row.get("exit_code", ""),
                ipc_aggregate_row.get("reason", ""),
                "",
                "",
                "",
                "",
                "",
                "",
                ipc_aggregate_row.get("gap_messages", ""),
                ipc_aggregate_row.get("ring_dropped_delta", ""),
                ipc_aggregate_row.get("committed_mismatch", ""),
                ipc_aggregate_row.get("crc_mismatch", ""),
                ipc_aggregate_row.get("payload_mismatch", ""),
                ipc_aggregate_row.get("observed_trades", ""),
                ipc_aggregate_row.get("artifact_csv", ""),
                ipc_aggregate_row.get("artifact_manifest", ""),
            ]
        )

        _emit(
            [
                "OVERALL",
                "m6_m7",
                "",
                "",
                "",
                "",
                int(bool(overall_ok)),
                "",
                "ok" if overall_ok else "failed",
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
                "",
                "",
                "",
            ]
        )


def _hft_scenario_name(lp: int, numa: int) -> str:
    numa_label = f"numa{numa}" if numa >= 0 else "numa_auto"
    return f"lp{lp}-{numa_label}"


def write_summary_markdown(
    path: Path,
    *,
    hft_rows: List[Dict],
    hft_aggregate_rows: Optional[List[Dict]] = None,
    hft_aggregate_gate: Optional[Dict] = None,
    ipc_rows: List[Dict],
    ipc_result: Dict,
    ipc_aggregate: Dict,
    overall_ok: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hft_aggregate_rows = list(hft_aggregate_rows or [])
    hft_aggregate_gate = dict(hft_aggregate_gate or {})
    lines: List[str] = []
    lines.append("# M6/M7 Evidence Summary")
    lines.append("")
    lines.append(f"- overall_ok: `{int(bool(overall_ok))}`")
    lines.append(f"- hft_windows: `{len(hft_rows)}`")
    lines.append(f"- hft_aggregate_enabled: `{int(bool(hft_aggregate_gate.get('enabled', False)))}`")
    lines.append(f"- hft_aggregate_ok: `{int(bool(hft_aggregate_gate.get('ok', True)))}`")
    lines.append(f"- ipc_windows: `{len(ipc_rows)}`")
    lines.append(f"- ipc_aggregate_enabled: `{int(bool(ipc_aggregate.get('enabled', False)))}`")
    lines.append(f"- ipc_aggregate_ok: `{int(bool(ipc_aggregate.get('ok', True)))}`")
    lines.append("")

    lines.append("## HFT")
    lines.append("")
    lines.append("| scenario | window | ok | reason | attempts | retried | p99(ns) | p999(ns) | target p99 | target p999 |")
    lines.append("| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in hft_rows:
        lines.append(
            "| {scenario} | {window} | {ok} | {reason} | {attempts} | {retried} | {p99} | {p999} | {tp99} | {tp999} |".format(
                scenario=row.get("scenario", ""),
                window=row.get("window_index", 1),
                ok=int(bool(row.get("ok", False))),
                reason=str(row.get("reason", "")),
                attempts=int(row.get("attempts", 1)),
                retried=int(bool(row.get("retried", False))),
                p99=int(row.get("actual_p99_ns", -1)),
                p999=int(row.get("actual_p999_ns", -1)),
                tp99=int(row.get("target_p99_ns", -1)),
                tp999=int(row.get("target_p999_ns", -1)),
            )
        )
    if not hft_rows:
        lines.append("| _none_ |  |  |  |  |  |  |  |  |  |")
    lines.append("")

    lines.append("## HFT Aggregate")
    lines.append("")
    lines.append("| scenario | windows | failed_windows | ok | reason | max p99(ns) | max p999(ns) | target p99 | target p999 |")
    lines.append("| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |")
    for row in hft_aggregate_rows:
        lines.append(
            "| {scenario} | {windows} | {failed} | {ok} | {reason} | {p99} | {p999} | {tp99} | {tp999} |".format(
                scenario=row.get("scenario", ""),
                windows=int(row.get("window_count", 0)),
                failed=int(row.get("failed_windows", 0)),
                ok=int(bool(row.get("ok", False))),
                reason=str(row.get("reason", "")),
                p99=int(row.get("max_actual_p99_ns", -1)),
                p999=int(row.get("max_actual_p999_ns", -1)),
                tp99=int(row.get("target_p99_ns", -1)),
                tp999=int(row.get("target_p999_ns", -1)),
            )
        )
    if not hft_aggregate_rows:
        lines.append("| _none_ |  |  |  |  |  |  |  |  |")
    lines.append("")
    lines.append(f"- aggregate_gate_enabled: `{int(bool(hft_aggregate_gate.get('enabled', False)))}`")
    lines.append(f"- aggregate_gate_ok: `{int(bool(hft_aggregate_gate.get('ok', True)))}`")
    lines.append(f"- aggregate_gate_reason: `{hft_aggregate_gate.get('reason', '')}`")
    if hft_aggregate_gate.get("enabled", False):
        lines.append(
            "- aggregate_limits: "
            f"failed_windows<={hft_aggregate_gate.get('max_failed_windows', -1)} "
            f"p99<={hft_aggregate_gate.get('max_p99_ns', -1)} "
            f"p999<={hft_aggregate_gate.get('max_p999_ns', -1)}"
        )
    lines.append("")

    lines.append("## IPC Windows")
    lines.append("")
    lines.append("| window | ok | reason | attempts | retried | gap_messages | ring_dropped_delta | observed_trades |")
    lines.append("| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in ipc_rows:
        lines.append(
            "| {window} | {ok} | {reason} | {attempts} | {retried} | {gap} | {dropped} | {observed} |".format(
                window=row.get("window_index", ""),
                ok=int(bool(row.get("ok", False))),
                reason=str(row.get("reason", "")),
                attempts=int(row.get("attempts", 1)),
                retried=int(bool(row.get("retried", False))),
                gap=int(row.get("gap_messages", -1)),
                dropped=int(row.get("ring_dropped_delta", -1)),
                observed=int(row.get("observed_trades", -1)),
            )
        )
    if not ipc_rows:
        lines.append("|  |  |  |  |  |  |  |  |")
    lines.append("")

    lines.append("## IPC Aggregate")
    lines.append("")
    lines.append(f"- ok: `{int(bool(ipc_result.get('ok', False)))}`")
    lines.append(f"- reason: `{ipc_result.get('reason', '')}`")
    lines.append(f"- gap_messages: `{ipc_result.get('gap_messages', -1)}`")
    lines.append(f"- ring_dropped_delta: `{ipc_result.get('ring_dropped_delta', -1)}`")
    lines.append(f"- observed_trades: `{ipc_result.get('observed_trades', -1)}`")
    lines.append(f"- aggregate_gate_enabled: `{int(bool(ipc_aggregate.get('enabled', False)))}`")
    lines.append(f"- aggregate_gate_ok: `{int(bool(ipc_aggregate.get('ok', True)))}`")
    lines.append(f"- aggregate_gate_reason: `{ipc_aggregate.get('reason', '')}`")
    if ipc_aggregate.get("enabled", False):
        lines.append(
            "- aggregate_limits: "
            f"gap<={ipc_aggregate.get('max_gap_messages', -1)} "
            f"ring<={ipc_aggregate.get('max_ring_dropped', -1)} "
            f"committed<={ipc_aggregate.get('max_committed_mismatch', -1)} "
            f"crc<={ipc_aggregate.get('max_crc_mismatch', -1)} "
            f"payload<={ipc_aggregate.get('max_payload_mismatch', -1)} "
            f"observed>={ipc_aggregate.get('min_observed_trades', -1)}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-exe", type=str, default=sys.executable)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--hft-script", type=Path, default=_ROOT / "scripts" / "benchmark_hft_qpc.py")
    ap.add_argument("--ipc-script", type=Path, default=_ROOT / "scripts" / "benchmark_ipc_zmq_vs_shm.py")
    ap.add_argument("--engine", type=Path, default=_ROOT / "engine" / "build" / "Release" / "engine.exe")
    ap.add_argument("--workdir", type=Path, default=_ROOT / "engine" / "build" / "Release")
    ap.add_argument("--hft-duration-seconds", type=float, default=3600.0)
    ap.add_argument("--hft-startup-grace-seconds", type=float, default=120.0)
    ap.add_argument("--hft-windows", type=lambda raw: parse_positive_int(raw, "hft-windows"), default=1)
    ap.add_argument("--hft-total-seconds", type=lambda raw: parse_positive_float(raw, "hft-total-seconds"), default=0.0)
    ap.add_argument("--hft-runs", type=str, default="baseline,pinned")
    ap.add_argument("--hft-enable-shm-qpc", action="store_true", default=False)
    ap.add_argument("--hft-qpc-sample-every", type=int, default=1)
    ap.add_argument("--hft-qpc-max-samples", type=int, default=1_000_000)
    ap.add_argument("--shm-qpc-sample-every", type=int, default=1)
    ap.add_argument("--shm-qpc-max-samples", type=int, default=1_000_000)
    ap.add_argument("--hft-main-core", type=int, default=0)
    ap.add_argument("--hft-publisher-core", type=int, default=1)
    ap.add_argument("--hft-profit-callback-core", type=int, default=2)
    ap.add_argument("--hft-core-index-mode", choices=["physical", "logical"], default="physical")
    ap.add_argument("--hft-prefetch", type=int, default=1)
    ap.add_argument("--hft-check-run", type=str, default="pinned")
    ap.add_argument("--hft-check-metric", type=str, default="shm_write_trade_duration")
    ap.add_argument("--hft-target-p99-ns", type=int, default=10_000)
    ap.add_argument("--hft-target-p999-ns", type=int, default=20_000)
    ap.add_argument(
        "--hft-aggregate-max-failed-windows",
        type=lambda raw: parse_optional_non_negative_int(raw, "hft-aggregate-max-failed-windows"),
        default=-1,
    )
    ap.add_argument(
        "--hft-aggregate-max-p99-ns",
        type=lambda raw: parse_optional_non_negative_int(raw, "hft-aggregate-max-p99-ns"),
        default=-1,
    )
    ap.add_argument(
        "--hft-aggregate-max-p999-ns",
        type=lambda raw: parse_optional_non_negative_int(raw, "hft-aggregate-max-p999-ns"),
        default=-1,
    )
    ap.add_argument("--hft-fail-on-check", action="store_true", default=False)
    ap.add_argument("--hft-shm-large-pages-strict", action="store_true", default=False)
    ap.add_argument("--hft-shm-prefetch-next-slot", type=int, default=1)
    ap.add_argument("--matrix-shm-large-pages", type=str, default="0,1")
    ap.add_argument("--matrix-shm-numa-nodes", type=str, default="-1,0")
    ap.add_argument("--session-seconds", type=float, default=21600.0)
    ap.add_argument("--session-windows", type=lambda raw: parse_positive_int(raw, "session-windows"), default=1)
    ap.add_argument("--session-total-seconds", type=lambda raw: parse_positive_float(raw, "session-total-seconds"), default=0.0)
    ap.add_argument("--session-shm-name", type=str, default=r"Local\PQMarketDataV1")
    ap.add_argument("--session-shm-mb", type=int, default=64)
    ap.add_argument("--session-max-gap-messages", type=int, default=0)
    ap.add_argument("--session-max-ring-dropped", type=int, default=0)
    ap.add_argument("--session-max-committed-mismatch", type=int, default=0)
    ap.add_argument("--session-max-crc-mismatch", type=int, default=0)
    ap.add_argument("--session-max-payload-mismatch", type=int, default=0)
    ap.add_argument("--session-min-observed-trades", type=int, default=0)
    ap.add_argument(
        "--session-aggregate-max-gap-messages",
        type=lambda raw: parse_optional_non_negative_int(raw, "session-aggregate-max-gap-messages"),
        default=-1,
    )
    ap.add_argument(
        "--session-aggregate-max-ring-dropped",
        type=lambda raw: parse_optional_non_negative_int(raw, "session-aggregate-max-ring-dropped"),
        default=-1,
    )
    ap.add_argument(
        "--session-aggregate-max-committed-mismatch",
        type=lambda raw: parse_optional_non_negative_int(raw, "session-aggregate-max-committed-mismatch"),
        default=-1,
    )
    ap.add_argument(
        "--session-aggregate-max-crc-mismatch",
        type=lambda raw: parse_optional_non_negative_int(raw, "session-aggregate-max-crc-mismatch"),
        default=-1,
    )
    ap.add_argument(
        "--session-aggregate-max-payload-mismatch",
        type=lambda raw: parse_optional_non_negative_int(raw, "session-aggregate-max-payload-mismatch"),
        default=-1,
    )
    ap.add_argument(
        "--session-aggregate-min-observed-trades",
        type=lambda raw: parse_optional_non_negative_int(raw, "session-aggregate-min-observed-trades"),
        default=-1,
    )
    ap.add_argument("--session-fail-on-loss", action="store_true", default=False)
    ap.add_argument("--session-producer-mode", choices=["engine", "external"], default="engine")
    ap.add_argument("--session-producer-lead-seconds", type=float, default=120.0)
    ap.add_argument("--session-producer-map-wait-seconds", type=float, default=120.0)
    ap.add_argument("--session-producer-ticker", type=str, default="WINFUT")
    ap.add_argument("--session-producer-bolsa", type=str, default="F")
    ap.add_argument("--hft-max-retries", type=lambda raw: parse_non_negative_int(raw, "hft-max-retries"), default=0)
    ap.add_argument("--ipc-max-retries", type=lambda raw: parse_non_negative_int(raw, "ipc-max-retries"), default=0)
    ap.add_argument("--retry-delay-seconds", type=float, default=3.0)
    ap.add_argument("--stop-on-error", action="store_true", default=False)
    ap.add_argument("--resume", action="store_true", default=False)
    ap.add_argument("--resume-allow-failed", action="store_true", default=False)
    ap.add_argument("--fail-on-any", action=argparse.BooleanOptionalAction, default=True)
    return ap


def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()
    env_bootstrap = bootstrap_runtime_env(_ROOT)

    if not args.hft_script.exists():
        raise SystemExit(f"hft script not found: {args.hft_script}")
    if not args.ipc_script.exists():
        raise SystemExit(f"ipc script not found: {args.ipc_script}")
    if not args.engine.exists():
        raise SystemExit(f"engine not found: {args.engine}")
    if not args.workdir.exists():
        raise SystemExit(f"workdir not found: {args.workdir}")

    lp_values = parse_binary_list(args.matrix_shm_large_pages, "matrix-shm-large-pages")
    numa_values = parse_int_list(args.matrix_shm_numa_nodes, "matrix-shm-numa-nodes")
    hft_runs = parse_token_list(args.hft_runs, "hft-runs")
    hft_windows = int(args.hft_windows)
    session_windows = int(args.session_windows)
    hft_scenario_count = len(lp_values) * len(numa_values)
    hft_run_count = len(hft_runs)
    hft_slot_count = hft_scenario_count * hft_windows * hft_run_count
    hft_window_seconds = resolve_hft_window_seconds(
        total_seconds=float(args.hft_total_seconds),
        window_seconds=float(args.hft_duration_seconds),
        windows=hft_windows,
        scenario_count=hft_scenario_count,
        run_count=hft_run_count,
    )
    hft_benchmark_duration_seconds = float(hft_window_seconds) + float(args.hft_startup_grace_seconds)
    session_window_seconds = resolve_window_seconds(
        total_seconds=float(args.session_total_seconds),
        window_seconds=float(args.session_seconds),
        windows=session_windows,
    )

    started = time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (_ROOT / "distributor" / "logs" / f"m6-m7-evidence-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    retry_delay_seconds = float(args.retry_delay_seconds)
    if retry_delay_seconds < 0:
        raise SystemExit("--retry-delay-seconds must be >= 0")
    if float(args.hft_startup_grace_seconds) < 0:
        raise SystemExit("--hft-startup-grace-seconds must be >= 0")
    if float(args.session_producer_lead_seconds) < 0:
        raise SystemExit("--session-producer-lead-seconds must be >= 0")
    if float(args.session_producer_map_wait_seconds) <= 0:
        raise SystemExit("--session-producer-map-wait-seconds must be > 0")

    hft_results: List[Dict] = []
    stop_due_error = False
    for lp in lp_values:
        for numa in numa_values:
            scenario = _hft_scenario_name(lp, numa)
            for window_index in range(1, hft_windows + 1):
                scenario_dir = out_dir / "hft" / scenario
                if hft_windows > 1:
                    scenario_dir = scenario_dir / f"window-{window_index:02d}"
                scenario_dir.mkdir(parents=True, exist_ok=True)
                out_csv = scenario_dir / "summary.csv"
                manifest_path = out_csv.with_suffix(".manifest.json")
                cmd = [
                    args.python_exe,
                    str(args.hft_script),
                    "--engine",
                    str(args.engine),
                    "--workdir",
                    str(args.workdir),
                    "--duration-seconds",
                    str(hft_benchmark_duration_seconds),
                    "--runs",
                    ",".join(hft_runs),
                    "--hft-qpc-sample-every",
                    str(args.hft_qpc_sample_every),
                    "--hft-qpc-max-samples",
                    str(args.hft_qpc_max_samples),
                    "--shm-qpc-sample-every",
                    str(args.shm_qpc_sample_every),
                    "--shm-qpc-max-samples",
                    str(args.shm_qpc_max_samples),
                    "--main-core",
                    str(args.hft_main_core),
                    "--publisher-core",
                    str(args.hft_publisher_core),
                    "--profit-callback-core",
                    str(args.hft_profit_callback_core),
                    "--hft-core-index-mode",
                    args.hft_core_index_mode,
                    "--hft-prefetch",
                    str(args.hft_prefetch),
                    "--shm-numa-node",
                    str(numa),
                    "--shm-prefetch-next-slot",
                    str(args.hft_shm_prefetch_next_slot),
                    "--check-run",
                    args.hft_check_run,
                    "--check-metric",
                    args.hft_check_metric,
                    "--target-p99-ns",
                    str(args.hft_target_p99_ns),
                    "--target-p999-ns",
                    str(args.hft_target_p999_ns),
                    "--out",
                    str(out_csv),
                ]
                if args.hft_enable_shm_qpc:
                    cmd.append("--enable-shm-qpc")
                if lp == 1:
                    cmd.append("--shm-large-pages")
                if args.hft_shm_large_pages_strict:
                    cmd.append("--shm-large-pages-strict")
                if args.hft_fail_on_check:
                    cmd.append("--fail-on-check")

                hft_resume_expected_args = _build_hft_resume_expected_args(
                    args,
                    hft_benchmark_duration_seconds=float(hft_benchmark_duration_seconds),
                    hft_runs=hft_runs,
                    lp=int(lp),
                    numa=int(numa),
                )
                resume_eval_info: Optional[Dict[str, Any]] = None
                hft_artifact_valid_for_resume = bool(
                    _can_resume_artifact(
                        out_csv,
                        manifest_path,
                        expected_args=hft_resume_expected_args,
                    )
                )
                if hft_artifact_valid_for_resume:
                    resume_manifest = _load_json(manifest_path)
                    resume_eval_info = evaluate_hft_manifest(
                        manifest=resume_manifest,
                        exit_code=0,
                        check_run=args.hft_check_run,
                        check_metric=args.hft_check_metric,
                    )
                skipped_existing = _should_reuse_existing_result(
                    resume_requested=bool(args.resume),
                    artifact_valid=hft_artifact_valid_for_resume,
                    eval_ok=bool((resume_eval_info or {}).get("ok", False)),
                    resume_allow_failed=bool(args.resume_allow_failed),
                )
                if skipped_existing:
                    run_info = {
                        "exit_code": 0,
                        "elapsed_s": 0.0,
                        "stdout_log": str(scenario_dir / "run.stdout.log"),
                        "stderr_log": str(scenario_dir / "run.stderr.log"),
                        "attempts": 1,
                        "retried": False,
                    }
                else:
                    def _run_hft_once() -> Dict:
                        run_info = run_command(
                            cmd=cmd,
                            cwd=_ROOT,
                            stdout_log=scenario_dir / "run.stdout.log",
                            stderr_log=scenario_dir / "run.stderr.log",
                        )
                        manifest = _load_json(manifest_path)
                        eval_info = evaluate_hft_manifest(
                            manifest=manifest,
                            exit_code=int(run_info["exit_code"]),
                            check_run=args.hft_check_run,
                            check_metric=args.hft_check_metric,
                        )
                        return {
                            **run_info,
                            **eval_info,
                        }

                    attempt_info = execute_with_retries(
                        run_once=_run_hft_once,
                        is_ok=lambda item: bool(item.get("ok", False)),
                        max_retries=int(args.hft_max_retries),
                        retry_delay_seconds=retry_delay_seconds,
                    )
                    run_info = {
                        "exit_code": int(attempt_info.get("exit_code", 0)),
                        "elapsed_s": float(attempt_info.get("elapsed_s", 0.0)),
                        "stdout_log": str(attempt_info.get("stdout_log", str(scenario_dir / "run.stdout.log"))),
                        "stderr_log": str(attempt_info.get("stderr_log", str(scenario_dir / "run.stderr.log"))),
                        "attempts": int(attempt_info.get("attempts", 1)),
                        "retried": bool(attempt_info.get("retried", False)),
                        "eval_info": {
                            "ok": bool(attempt_info.get("ok", False)),
                            "reason": str(attempt_info.get("reason", "check_failed")),
                            "check_run": str(attempt_info.get("check_run", args.hft_check_run)),
                            "check_metric": str(attempt_info.get("check_metric", args.hft_check_metric)),
                            "actual_p99_ns": int(attempt_info.get("actual_p99_ns", -1)),
                            "actual_p999_ns": int(attempt_info.get("actual_p999_ns", -1)),
                            "target_p99_ns": int(attempt_info.get("target_p99_ns", -1)),
                            "target_p999_ns": int(attempt_info.get("target_p999_ns", -1)),
                        },
                    }

                if skipped_existing:
                    eval_info = dict(resume_eval_info or {})
                else:
                    eval_info = dict(run_info.pop("eval_info"))
                row = {
                    "scenario": scenario,
                    "window_index": window_index,
                    "lp": lp,
                    "numa": numa,
                    "exit_code": int(run_info["exit_code"]),
                    "elapsed_s": float(run_info["elapsed_s"]),
                    "artifact_csv": str(out_csv),
                    "artifact_manifest": str(manifest_path),
                    "stdout_log": run_info["stdout_log"],
                    "stderr_log": run_info["stderr_log"],
                    "skipped_existing": skipped_existing,
                    "attempts": int(run_info.get("attempts", 1)),
                    "retried": bool(run_info.get("retried", False)),
                    **eval_info,
                }
                hft_results.append(row)

                if args.stop_on_error and not row["ok"]:
                    stop_due_error = True
                    break
            if stop_due_error:
                break
        if stop_due_error:
            break

    ipc_results: List[Dict] = []
    for window_index in range(1, session_windows + 1):
        ipc_dir = out_dir / "ipc"
        if session_windows > 1:
            ipc_dir = ipc_dir / f"window-{window_index:02d}"
        ipc_dir.mkdir(parents=True, exist_ok=True)
        ipc_csv = ipc_dir / "session.csv"
        ipc_manifest_path = ipc_csv.with_suffix(".manifest.json")
        row: Dict
        if stop_due_error:
            row = {
                "scenario": "session",
                "window_index": window_index if session_windows > 1 else "",
                "exit_code": -1,
                "elapsed_s": 0.0,
                "artifact_csv": str(ipc_csv),
                "artifact_manifest": str(ipc_manifest_path),
                "stdout_log": "",
                "stderr_log": "",
                "skipped_existing": False,
                "attempts": 0,
                "retried": False,
                "ok": False,
                "reason": "skipped_due_hft_error",
                "gap_messages": -1,
                "ring_dropped_delta": -1,
                "committed_mismatch": -1,
                "crc_mismatch": -1,
                "payload_mismatch": -1,
                "observed_trades": -1,
                "session_ok": 0,
                "max_gap_messages_allowed": args.session_max_gap_messages,
                "max_ring_dropped_allowed": args.session_max_ring_dropped,
                "max_committed_mismatch_allowed": args.session_max_committed_mismatch,
                "max_crc_mismatch_allowed": args.session_max_crc_mismatch,
                "max_payload_mismatch_allowed": args.session_max_payload_mismatch,
                "min_observed_trades_allowed": args.session_min_observed_trades,
            }
            ipc_results.append(row)
            continue

        ipc_cmd = [
            args.python_exe,
            str(args.ipc_script),
            "--session",
            "--out",
            str(ipc_csv),
            "--shm-name",
            args.session_shm_name,
            "--shm-mb",
            str(args.session_shm_mb),
            "--session-seconds",
            str(session_window_seconds),
            "--session-max-gap-messages",
            str(args.session_max_gap_messages),
            "--session-max-ring-dropped",
            str(args.session_max_ring_dropped),
            "--session-max-committed-mismatch",
            str(args.session_max_committed_mismatch),
            "--session-max-crc-mismatch",
            str(args.session_max_crc_mismatch),
            "--session-max-payload-mismatch",
            str(args.session_max_payload_mismatch),
            "--session-min-observed-trades",
            str(args.session_min_observed_trades),
        ]
        if args.session_fail_on_loss:
            ipc_cmd.append("--session-fail-on-loss")

        ipc_resume_expected_args = _build_ipc_resume_expected_args(
            args,
            session_window_seconds=float(session_window_seconds),
        )
        ipc_resume_eval: Optional[Dict[str, Any]] = None
        ipc_artifact_valid_for_resume = bool(
            _can_resume_artifact(
                ipc_csv,
                ipc_manifest_path,
                expected_args=ipc_resume_expected_args,
            )
        )
        if ipc_artifact_valid_for_resume:
            ipc_resume_manifest = _load_json(ipc_manifest_path)
            ipc_resume_eval = evaluate_ipc_session_manifest(ipc_resume_manifest, exit_code=0)
        ipc_skipped_existing = _should_reuse_existing_result(
            resume_requested=bool(args.resume),
            artifact_valid=ipc_artifact_valid_for_resume,
            eval_ok=bool((ipc_resume_eval or {}).get("ok", False)),
            resume_allow_failed=bool(args.resume_allow_failed),
        )
        if ipc_skipped_existing:
            ipc_run = {
                "exit_code": 0,
                "elapsed_s": 0.0,
                "stdout_log": str(ipc_dir / "run.stdout.log"),
                "stderr_log": str(ipc_dir / "run.stderr.log"),
                "attempts": 1,
                "retried": False,
            }
            ipc_eval = dict(ipc_resume_eval or {})
        else:
            def _run_ipc_once() -> Dict:
                mapping_probe = _probe_session_mapping(args.session_shm_name)
                producer_proc: Optional[subprocess.Popen] = None
                producer_stdout_handle = None
                producer_stderr_handle = None
                producer_stdout_log = ""
                producer_stderr_log = ""
                producer_started = False
                producer_bootstrap_reason = "external_mapping"
                if not bool(mapping_probe.get("ok", False)) and str(args.session_producer_mode).strip().lower() == "engine":
                    producer = _start_ipc_engine_producer(
                        args=args,
                        ipc_dir=ipc_dir,
                        session_window_seconds=float(session_window_seconds),
                    )
                    producer_proc = producer["process"]
                    producer_stdout_handle = producer["stdout_handle"]
                    producer_stderr_handle = producer["stderr_handle"]
                    producer_stdout_log = str(producer["stdout_log"])
                    producer_stderr_log = str(producer["stderr_log"])
                    producer_started = True
                    mapping_probe = _wait_for_session_mapping(
                        args.session_shm_name,
                        timeout_seconds=float(args.session_producer_map_wait_seconds),
                    )
                    producer_bootstrap_reason = str(mapping_probe.get("reason", "mapping_not_found"))
                elif not bool(mapping_probe.get("ok", False)):
                    producer_bootstrap_reason = str(mapping_probe.get("reason", "mapping_not_found"))

                try:
                    ipc_run = run_command(
                        cmd=ipc_cmd,
                        cwd=_ROOT,
                        stdout_log=ipc_dir / "run.stdout.log",
                        stderr_log=ipc_dir / "run.stderr.log",
                    )
                    ipc_manifest = _load_json(ipc_manifest_path)
                    ipc_eval = evaluate_ipc_session_manifest(ipc_manifest, int(ipc_run["exit_code"]))
                finally:
                    if producer_proc is not None:
                        _stop_background_process(producer_proc, timeout_seconds=10.0)
                    if producer_stdout_handle is not None:
                        producer_stdout_handle.close()
                    if producer_stderr_handle is not None:
                        producer_stderr_handle.close()

                if (
                    not bool(mapping_probe.get("ok", False))
                    and str(ipc_eval.get("reason", "")).strip().lower() in ("session_gate_failed", "session_mapping_not_found")
                ):
                    ipc_eval["ok"] = False
                    ipc_eval["session_ok"] = 0
                    ipc_eval["reason"] = "session_mapping_not_found"
                if (
                    producer_started
                    and str(ipc_eval.get("reason", "")).strip().lower()
                    in ("session_gate_failed", "session_no_shm_writes", "session_observed_below_min")
                    and _producer_log_indicates_market_not_connected(producer_stderr_log)
                ):
                    ipc_eval["ok"] = False
                    ipc_eval["session_ok"] = 0
                    ipc_eval["reason"] = "market_not_connected"
                ipc_eval["mapping_ready"] = 1 if bool(mapping_probe.get("ok", False)) else 0
                ipc_eval["mapping_probe_reason"] = str(mapping_probe.get("reason", "unknown"))
                ipc_eval["mapping_probe_candidate"] = str(mapping_probe.get("candidate", ""))
                ipc_eval["producer_started"] = 1 if producer_started else 0
                ipc_eval["producer_bootstrap_reason"] = producer_bootstrap_reason
                ipc_eval["producer_stdout_log"] = producer_stdout_log if producer_started else ""
                ipc_eval["producer_stderr_log"] = producer_stderr_log if producer_started else ""
                return {**ipc_run, **ipc_eval}

            ipc_attempt = execute_with_retries(
                run_once=_run_ipc_once,
                is_ok=lambda item: bool(item.get("ok", False)),
                max_retries=int(args.ipc_max_retries),
                retry_delay_seconds=retry_delay_seconds,
            )
            ipc_run = {
                "exit_code": int(ipc_attempt.get("exit_code", 0)),
                "elapsed_s": float(ipc_attempt.get("elapsed_s", 0.0)),
                "stdout_log": str(ipc_attempt.get("stdout_log", str(ipc_dir / "run.stdout.log"))),
                "stderr_log": str(ipc_attempt.get("stderr_log", str(ipc_dir / "run.stderr.log"))),
                "attempts": int(ipc_attempt.get("attempts", 1)),
                "retried": bool(ipc_attempt.get("retried", False)),
            }
            ipc_eval = {
                "ok": bool(ipc_attempt.get("ok", False)),
                "reason": str(ipc_attempt.get("reason", "session_gate_failed")),
                "gap_messages": int(ipc_attempt.get("gap_messages", -1)),
                "ring_dropped_delta": int(ipc_attempt.get("ring_dropped_delta", -1)),
                "committed_mismatch": int(ipc_attempt.get("committed_mismatch", -1)),
                "crc_mismatch": int(ipc_attempt.get("crc_mismatch", -1)),
                "payload_mismatch": int(ipc_attempt.get("payload_mismatch", -1)),
                "observed_trades": int(ipc_attempt.get("observed_trades", -1)),
                "session_ok": int(ipc_attempt.get("session_ok", 0)),
                "max_gap_messages_allowed": int(ipc_attempt.get("max_gap_messages_allowed", -1)),
                "max_ring_dropped_allowed": int(ipc_attempt.get("max_ring_dropped_allowed", -1)),
                "max_committed_mismatch_allowed": int(ipc_attempt.get("max_committed_mismatch_allowed", -1)),
                "max_crc_mismatch_allowed": int(ipc_attempt.get("max_crc_mismatch_allowed", -1)),
                "max_payload_mismatch_allowed": int(ipc_attempt.get("max_payload_mismatch_allowed", -1)),
                "min_observed_trades_allowed": int(ipc_attempt.get("min_observed_trades_allowed", -1)),
                "session_error": str(ipc_attempt.get("session_error", "")),
                "mapping_ready": int(ipc_attempt.get("mapping_ready", 0)),
                "mapping_probe_reason": str(ipc_attempt.get("mapping_probe_reason", "")),
                "mapping_probe_candidate": str(ipc_attempt.get("mapping_probe_candidate", "")),
                "producer_started": int(ipc_attempt.get("producer_started", 0)),
                "producer_bootstrap_reason": str(ipc_attempt.get("producer_bootstrap_reason", "")),
                "producer_stdout_log": str(ipc_attempt.get("producer_stdout_log", "")),
                "producer_stderr_log": str(ipc_attempt.get("producer_stderr_log", "")),
            }

        row = {
            "scenario": "session",
            "window_index": window_index if session_windows > 1 else "",
            "exit_code": int(ipc_run["exit_code"]),
            "elapsed_s": float(ipc_run["elapsed_s"]),
            "artifact_csv": str(ipc_csv),
            "artifact_manifest": str(ipc_manifest_path),
            "stdout_log": ipc_run["stdout_log"],
            "stderr_log": ipc_run["stderr_log"],
            "skipped_existing": ipc_skipped_existing,
            "attempts": int(ipc_run.get("attempts", 1)),
            "retried": bool(ipc_run.get("retried", False)),
            **ipc_eval,
        }
        ipc_results.append(row)

    ipc_result = aggregate_ipc_results(ipc_results)
    hft_aggregate_results = aggregate_hft_results(hft_results)
    hft_aggregate_gate = evaluate_hft_aggregate_gates(
        hft_aggregate_results,
        max_failed_windows=int(args.hft_aggregate_max_failed_windows),
        max_p99_ns=int(args.hft_aggregate_max_p99_ns),
        max_p999_ns=int(args.hft_aggregate_max_p999_ns),
    )
    ipc_aggregate = evaluate_ipc_aggregate_gates(
        ipc_result,
        max_gap_messages=int(args.session_aggregate_max_gap_messages),
        max_ring_dropped=int(args.session_aggregate_max_ring_dropped),
        max_committed_mismatch=int(args.session_aggregate_max_committed_mismatch),
        max_crc_mismatch=int(args.session_aggregate_max_crc_mismatch),
        max_payload_mismatch=int(args.session_aggregate_max_payload_mismatch),
        min_observed_trades=int(args.session_aggregate_min_observed_trades),
    )
    fail_on_any_blocked = should_fail_on_any(
        hft_rows=hft_results,
        ipc_rows=ipc_results,
        hft_aggregate_gate=hft_aggregate_gate,
        ipc_aggregate_gate=ipc_aggregate,
    )

    overall_ok = bool(
        all(bool(item.get("ok")) for item in hft_results)
        and all(bool(item.get("ok")) for item in ipc_results)
        and bool(hft_aggregate_gate.get("ok", True))
        and bool(ipc_aggregate.get("ok", True))
    )

    summary_csv = out_dir / "summary.csv"
    write_summary_csv(
        summary_csv,
        hft_results,
        ipc_results,
        ipc_result,
        overall_ok,
        hft_aggregate_rows=hft_aggregate_results,
        hft_aggregate_gate=hft_aggregate_gate,
    )
    summary_markdown = out_dir / "summary.md"
    write_summary_markdown(
        summary_markdown,
        hft_rows=hft_results,
        hft_aggregate_rows=hft_aggregate_results,
        hft_aggregate_gate=hft_aggregate_gate,
        ipc_rows=ipc_results,
        ipc_result=ipc_result,
        ipc_aggregate=ipc_aggregate,
        overall_ok=overall_ok,
    )

    summary_manifest = out_dir / "summary.manifest.json"

    payload = {
        "started_at_epoch_s": started,
        "finished_at_epoch_s": time.time(),
        "overall_ok": overall_ok,
        "fail_on_any_blocked": bool(fail_on_any_blocked),
        "non_fatal_failure_reasons": ["market_not_connected"],
        "args": {
            "env_bootstrap": {
                "dotenv_loaded": sorted(set(env_bootstrap.get("dotenv", []))),
                "kms_loaded": sorted(set(env_bootstrap.get("kms", []))),
                "aliases_applied": sorted(set(env_bootstrap.get("aliases", []))),
            },
            "hft_duration_seconds": float(args.hft_duration_seconds),
            "hft_total_seconds": float(args.hft_total_seconds),
            "hft_window_seconds_effective": float(hft_window_seconds),
            "hft_startup_grace_seconds": float(args.hft_startup_grace_seconds),
            "hft_benchmark_duration_seconds": float(hft_benchmark_duration_seconds),
            "hft_windows": hft_windows,
            "hft_runs": ",".join(hft_runs),
            "hft_scenario_count": int(hft_scenario_count),
            "hft_run_count": int(hft_run_count),
            "hft_slot_count": int(hft_slot_count),
            "hft_enable_shm_qpc": bool(args.hft_enable_shm_qpc),
            "hft_core_index_mode": args.hft_core_index_mode,
            "hft_check_run": args.hft_check_run,
            "hft_check_metric": args.hft_check_metric,
            "hft_target_p99_ns": int(args.hft_target_p99_ns),
            "hft_target_p999_ns": int(args.hft_target_p999_ns),
            "hft_aggregate_max_failed_windows": int(args.hft_aggregate_max_failed_windows),
            "hft_aggregate_max_p99_ns": int(args.hft_aggregate_max_p99_ns),
            "hft_aggregate_max_p999_ns": int(args.hft_aggregate_max_p999_ns),
            "matrix_shm_large_pages": args.matrix_shm_large_pages,
            "matrix_shm_numa_nodes": args.matrix_shm_numa_nodes,
            "session_seconds": float(args.session_seconds),
            "session_total_seconds": float(args.session_total_seconds),
            "session_window_seconds_effective": float(session_window_seconds),
            "session_windows": session_windows,
            "session_shm_name": args.session_shm_name,
            "session_shm_mb": int(args.session_shm_mb),
            "session_max_gap_messages": int(args.session_max_gap_messages),
            "session_max_ring_dropped": int(args.session_max_ring_dropped),
            "session_max_committed_mismatch": int(args.session_max_committed_mismatch),
            "session_max_crc_mismatch": int(args.session_max_crc_mismatch),
            "session_max_payload_mismatch": int(args.session_max_payload_mismatch),
            "session_min_observed_trades": int(args.session_min_observed_trades),
            "session_aggregate_max_gap_messages": int(args.session_aggregate_max_gap_messages),
            "session_aggregate_max_ring_dropped": int(args.session_aggregate_max_ring_dropped),
            "session_aggregate_max_committed_mismatch": int(args.session_aggregate_max_committed_mismatch),
            "session_aggregate_max_crc_mismatch": int(args.session_aggregate_max_crc_mismatch),
            "session_aggregate_max_payload_mismatch": int(args.session_aggregate_max_payload_mismatch),
            "session_aggregate_min_observed_trades": int(args.session_aggregate_min_observed_trades),
            "session_fail_on_loss": bool(args.session_fail_on_loss),
            "session_producer_mode": str(args.session_producer_mode),
            "session_producer_lead_seconds": float(args.session_producer_lead_seconds),
            "session_producer_map_wait_seconds": float(args.session_producer_map_wait_seconds),
            "session_producer_ticker": str(args.session_producer_ticker),
            "session_producer_bolsa": str(args.session_producer_bolsa),
            "hft_max_retries": int(args.hft_max_retries),
            "ipc_max_retries": int(args.ipc_max_retries),
            "retry_delay_seconds": float(args.retry_delay_seconds),
            "stop_on_error": bool(args.stop_on_error),
            "resume": bool(args.resume),
            "resume_allow_failed": bool(args.resume_allow_failed),
            "fail_on_any": bool(args.fail_on_any),
        },
        "hft": hft_results,
        "hft_aggregate": hft_aggregate_results,
        "hft_aggregate_gate": hft_aggregate_gate,
        "ipc_sessions": ipc_results,
        "ipc_session": ipc_result,
        "ipc_aggregate_gate": ipc_aggregate,
        "artifacts": {
            "summary_csv": str(summary_csv),
            "summary_markdown": str(summary_markdown),
            "summary_manifest": str(summary_manifest),
        },
    }
    summary_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {summary_markdown}")
    print(f"Wrote: {summary_manifest}")
    if args.fail_on_any and fail_on_any_blocked:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
