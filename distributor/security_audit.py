"""Shared JSONL security audit writer with basic retention and metrics."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

_lock = threading.Lock()
_last_prune_by_target: dict[str, float] = {}
_metrics: dict[str, Any] = {
    "writes_ok": 0,
    "writes_failed": 0,
    "pruned_files": 0,
    "prune_errors": 0,
    "last_prune_ts_utc": "",
    "source_counts": {},
    "status_counts": {},
}


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _parse_non_negative_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _audit_target_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _iter_retention_candidates(base_path: Path) -> list[Path]:
    candidates: list[Path] = []
    if base_path.exists() and base_path.is_file():
        candidates.append(base_path)

    stem = base_path.stem
    suffix = base_path.suffix or ".jsonl"
    parent = base_path.parent if str(base_path.parent) else Path(".")
    pattern = f"{stem}-*{suffix}"
    for entry in parent.glob(pattern):
        if entry.is_file():
            candidates.append(entry)
    return candidates


def _prune_old_files(base_path: Path, retention_days: int, now_utc: datetime) -> tuple[int, int]:
    if retention_days <= 0:
        return 0, 0
    cutoff_ts = (now_utc - timedelta(days=retention_days)).timestamp()
    pruned = 0
    errors = 0
    for candidate in _iter_retention_candidates(base_path):
        try:
            stat = candidate.stat()
            if stat.st_mtime < cutoff_ts:
                candidate.unlink()
                pruned += 1
        except OSError:
            errors += 1
    return pruned, errors


def _resolve_write_path(base_path: Path, now_utc: datetime, daily_rotate: bool) -> Path:
    if not daily_rotate:
        return base_path
    suffix = base_path.suffix or ".jsonl"
    stem = base_path.stem
    filename = f"{stem}-{now_utc.strftime('%Y%m%d')}{suffix}"
    return base_path.with_name(filename)


def _inc_counter(container: dict[str, int], key: str) -> None:
    container[key] = int(container.get(key, 0)) + 1


def write_security_audit(
    path: str | None,
    payload: Mapping[str, Any],
    *,
    source: str,
    env: Mapping[str, str] | None = None,
) -> None:
    if not path:
        return

    effective_env = env if env is not None else os.environ
    retention_days = _parse_non_negative_int(
        effective_env.get("SECURITY_AUDIT_RETENTION_DAYS"),
        0,
    )
    prune_interval_s = _parse_non_negative_int(
        effective_env.get("SECURITY_AUDIT_PRUNE_INTERVAL_S"),
        300,
    )
    daily_rotate = _is_truthy(effective_env.get("SECURITY_AUDIT_DAILY_ROTATE"))

    base_path = Path(path)
    now_utc = datetime.now(timezone.utc)
    now_epoch = now_utc.timestamp()
    target_key = _audit_target_key(base_path)

    if retention_days > 0:
        should_prune = False
        with _lock:
            last_prune = _last_prune_by_target.get(target_key, 0.0)
            if prune_interval_s == 0 or (now_epoch - last_prune) >= prune_interval_s:
                should_prune = True
                _last_prune_by_target[target_key] = now_epoch
        if should_prune:
            pruned, errors = _prune_old_files(base_path, retention_days, now_utc)
            with _lock:
                _metrics["pruned_files"] = int(_metrics["pruned_files"]) + pruned
                _metrics["prune_errors"] = int(_metrics["prune_errors"]) + errors
                _metrics["last_prune_ts_utc"] = now_utc.isoformat()

    target_path = _resolve_write_path(base_path, now_utc, daily_rotate)
    record = dict(payload)
    record["ts_utc"] = now_utc.isoformat()
    record["source"] = source
    status = str(record.get("status", "unknown"))

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        with _lock:
            _metrics["writes_failed"] = int(_metrics["writes_failed"]) + 1
            _inc_counter(_metrics["source_counts"], source)
            _inc_counter(_metrics["status_counts"], f"{source}:write_failed")
        return

    with _lock:
        _metrics["writes_ok"] = int(_metrics["writes_ok"]) + 1
        _inc_counter(_metrics["source_counts"], source)
        _inc_counter(_metrics["status_counts"], f"{source}:{status}")


def security_audit_metrics() -> dict[str, Any]:
    with _lock:
        return {
            "writes_ok": int(_metrics["writes_ok"]),
            "writes_failed": int(_metrics["writes_failed"]),
            "pruned_files": int(_metrics["pruned_files"]),
            "prune_errors": int(_metrics["prune_errors"]),
            "last_prune_ts_utc": str(_metrics["last_prune_ts_utc"]),
            "source_counts": dict(_metrics["source_counts"]),
            "status_counts": dict(_metrics["status_counts"]),
        }


def reset_security_audit_metrics() -> None:
    with _lock:
        _last_prune_by_target.clear()
        _metrics["writes_ok"] = 0
        _metrics["writes_failed"] = 0
        _metrics["pruned_files"] = 0
        _metrics["prune_errors"] = 0
        _metrics["last_prune_ts_utc"] = ""
        _metrics["source_counts"] = {}
        _metrics["status_counts"] = {}
