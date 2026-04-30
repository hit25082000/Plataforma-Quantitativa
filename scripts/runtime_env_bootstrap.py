#!/usr/bin/env python3
"""Runtime environment bootstrap for local evidence scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


_ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _is_truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _parse_env_value(raw: str) -> str:
    value = str(raw).strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    comment_idx = value.find(" #")
    if comment_idx >= 0:
        value = value[:comment_idx]
    return value.strip()


def _load_dotenv_file(path: Path, *, preserve_existing: bool) -> List[str]:
    if not path.exists():
        return []

    loaded: List[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key = m.group(1).strip()
        value = _parse_env_value(m.group(2))
        if preserve_existing and str(os.environ.get(key, "")).strip():
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


def _apply_aliases() -> List[str]:
    alias_pairs = [
        ("PROFIT_ACTIVATION_KEY", "DLL_KEY"),
        ("PROFIT_ACTIVATION_KEY", "PROFIT_DLL_ACTIVATION_KEY"),
        ("PROFIT_DLL_ACTIVATION_KEY", "PROFIT_ACTIVATION_KEY"),
        ("PROFIT_USER", "PROFIT_DLL_USER"),
        ("PROFIT_DLL_USER", "PROFIT_USER"),
        ("PROFIT_PASSWORD", "PROFIT_DLL_PASSWORD"),
        ("PROFIT_DLL_PASSWORD", "PROFIT_PASSWORD"),
    ]
    applied: List[str] = []
    for target, source in alias_pairs:
        if str(os.environ.get(target, "")).strip():
            continue
        source_value = str(os.environ.get(source, "")).strip()
        if not source_value:
            continue
        os.environ[target] = source_value
        applied.append(f"{source}->{target}")
    return applied


def _load_kms_secrets_if_enabled(root: Path) -> List[str]:
    enabled = _is_truthy(os.environ.get("AWS_KMS_ENABLED")) or _is_truthy(os.environ.get("KMS_ENABLED"))
    if not enabled:
        return []

    loader = root / "scripts" / "load_kms_secrets.py"
    if not loader.exists():
        raise RuntimeError(f"KMS loader not found: {loader}")

    proc = subprocess.run(
        [sys.executable, str(loader), "--json-values"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"KMS bootstrap failed: {detail}")

    text = (proc.stdout or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"KMS bootstrap returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        return []

    loaded: List[str] = []
    for key, value in payload.items():
        env_name = str(key).strip()
        if not env_name:
            continue
        os.environ[env_name] = str(value)
        loaded.append(env_name)
    return loaded


def bootstrap_runtime_env(root: Path) -> Dict[str, List[str]]:
    """Load local/KMS secrets and apply aliases used by engine scripts."""
    root = Path(root).resolve()
    report: Dict[str, List[str]] = {
        "dotenv": [],
        "kms": [],
        "aliases": [],
    }

    report["dotenv"].extend(_load_dotenv_file(root / ".env", preserve_existing=True))
    report["dotenv"].extend(_load_dotenv_file(root / ".env.local", preserve_existing=True))
    report["kms"].extend(_load_kms_secrets_if_enabled(root))
    report["aliases"].extend(_apply_aliases())
    return report

