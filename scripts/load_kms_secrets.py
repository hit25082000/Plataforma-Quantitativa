"""Load AWS KMS-backed secrets and emit them for parent process injection."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_bootstrap_module():
    root = Path(__file__).resolve().parent.parent
    distributor_dir = root / "distributor"
    if str(distributor_dir) not in sys.path:
        sys.path.insert(0, str(distributor_dir))
    from aws_kms_bootstrap import bootstrap_aws_kms_env

    return bootstrap_aws_kms_env


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load AWS KMS secrets into environment.")
    parser.add_argument(
        "--json-values",
        action="store_true",
        help="Print JSON map with loaded env var values (for caller process injection).",
    )
    args = parser.parse_args()

    enabled = _is_truthy(os.environ.get("AWS_KMS_ENABLED")) or _is_truthy(
        os.environ.get("KMS_ENABLED")
    )
    if not enabled:
        print("{}" if args.json_values else "[]")
        return 0

    try:
        bootstrap_aws_kms_env = _load_bootstrap_module()
        loaded = bootstrap_aws_kms_env()
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2

    if args.json_values:
        values = {name: os.environ.get(name, "") for name in loaded.keys()}
        print(json.dumps(values, ensure_ascii=False))
    else:
        print(json.dumps(sorted(loaded.keys()), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

