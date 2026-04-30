#!/usr/bin/env python3
"""
Evidência rápida do backend SQL de views materializadas (M9).

- Ingestão de trade/dom no backend sqlite
- Consulta de agregados
- Restart lógico (nova instância) e validação de persistência
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG views sqlite evidence runner")
    parser.add_argument(
        "--out-dir",
        default="distributor/logs/rag-views-sqlite-evidence",
        help="Diretório de saída para artifacts (summary.json)",
    )
    parser.add_argument(
        "--sqlite-path",
        default="",
        help="Path do sqlite (default: <out-dir>/rag_views.sqlite3)",
    )
    return parser.parse_args()


def _build_engine(*, sqlite_path: str):
    root = Path(__file__).resolve().parent.parent
    dist = root / "distributor"
    if str(dist) not in sys.path:
        sys.path.insert(0, str(dist))
    import realtime_rag as rr

    return rr.RealtimeRagEngine(
        enabled=True,
        window_seconds=300,
        ttl_seconds=3600,
        top_k=3,
        max_context_chars=2000,
        redpanda_brokers="",
        topic_prefix="pq",
        retention_ms=28800000,
        views_enabled=True,
        views_backend="sqlite",
        views_sqlite_path=sqlite_path,
    )


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = str((Path(args.sqlite_path).resolve() if args.sqlite_path else (out_dir / "rag_views.sqlite3")))

    now_ms = int(time.time() * 1000)
    eng_a = _build_engine(sqlite_path=sqlite_path)
    eng_a.ingest(
        {
            "topic": "market",
            "type": "trade",
            "ticker": "WINFUT",
            "price": 130100.0,
            "qty": 50,
            "net_aggression": 120,
            "buy_agent": 111,
            "sell_agent": 222,
            "ts": now_ms - 1200,
        }
    )
    eng_a.ingest(
        {
            "topic": "market",
            "type": "dom_snapshot",
            "ticker": "WINFUT",
            "buy": [{"price": 130095.0, "qty": 900}],
            "sell": [{"price": 130105.0, "qty": 700}],
            "ts": now_ms - 600,
        }
    )

    before_restart = eng_a.materialized_view(ticker="WINFUT", lookback_seconds=300)
    eng_b = _build_engine(sqlite_path=sqlite_path)
    after_restart = eng_b.materialized_view(ticker="WINFUT", lookback_seconds=300)

    checks: dict[str, Any] = {
        "before_enabled": bool(before_restart.get("enabled")),
        "before_trade_count": int(before_restart.get("trade_count", 0)),
        "after_enabled": bool(after_restart.get("enabled")),
        "after_trade_count": int(after_restart.get("trade_count", 0)),
        "after_trade_qty_sum": int(after_restart.get("trade_qty_sum", 0)),
        "after_aggression_delta": int(after_restart.get("aggression_delta", 0)),
        "after_latest_wall_count": int(after_restart.get("latest_wall_count", 0)),
    }
    success = (
        checks["before_enabled"]
        and checks["after_enabled"]
        and checks["before_trade_count"] >= 1
        and checks["after_trade_count"] >= 1
        and checks["after_trade_qty_sum"] >= 50
        and checks["after_latest_wall_count"] >= 2
    )

    summary = {
        "ok": bool(success),
        "sqlite_path": sqlite_path,
        "checks": checks,
        "before_restart": before_restart,
        "after_restart": after_restart,
        "ts": now_ms,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")

    print(json.dumps({"ok": bool(success), "summary": str(summary_path)}, ensure_ascii=True))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())

