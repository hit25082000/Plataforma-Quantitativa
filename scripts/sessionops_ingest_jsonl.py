#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "distributor"
if str(DIST_DIR) not in sys.path:
    sys.path.insert(0, str(DIST_DIR))

from sessionops_contract import coerce_legacy_ocr_trace_row, new_session_context
from sessionops_store import SessionOpsStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Indexa eventos SessionOps/OCR JSONL em SQLite.")
    p.add_argument("--jsonl", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--poll-seconds", type=float, default=1.0)
    p.add_argument("--oneshot", action="store_true", default=False)
    return p.parse_args()


def ingest_file(path: Path, store: SessionOpsStore, offset: int, ctx) -> int:
    if not path.exists():
        return offset
    with path.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        while True:
            raw = fh.readline()
            if not raw:
                break
            offset = fh.tell()
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if "sessionops_contract_version" not in row:
                row = coerce_legacy_ocr_trace_row(row, default_ctx=ctx)
            store.upsert_event(row)
    return offset


def main() -> int:
    args = parse_args()
    store = SessionOpsStore(args.db)
    ctx = new_session_context(component="ocr", build="legacy-trace")
    offset = 0
    while True:
        offset = ingest_file(args.jsonl, store, offset, ctx)
        if args.oneshot:
            break
        time.sleep(max(0.1, float(args.poll_seconds)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
