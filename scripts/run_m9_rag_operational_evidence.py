#!/usr/bin/env python3
"""
Evidência operacional contínua do M9 (RAG intraday).

Recursos operacionais:
- warm-up obrigatório antes da janela principal
- watchdog de disponibilidade HTTP (/health)
- rerun automático de tentativa quando há queda de health
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _request_json(url: str, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M9 RAG operational evidence runner.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL do distributor")
    parser.add_argument("--ticker", default="WINFUT", help="Ticker para consultar /api/rag/views")
    parser.add_argument("--duration-seconds", type=float, default=120.0, help="Duração total da coleta principal")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Intervalo entre amostras")
    parser.add_argument("--timeout-seconds", type=float, default=4.0, help="Timeout HTTP por chamada")
    parser.add_argument("--out-dir", default="", help="Diretório raiz de saída (default timestamp em distributor/logs)")
    parser.add_argument("--expect-views-backend", default="", help="Backend esperado (sqlite/memory)")
    parser.add_argument("--max-http-failures", type=int, default=3, help="Máximo de falhas HTTP permitidas")
    parser.add_argument("--max-lag-ms", type=int, default=30000, help="Lag máximo aceitável para view")
    parser.add_argument(
        "--sqlite-path",
        default="",
        help="Fallback de evidência via SQLite local (ex.: distributor/logs/rag_views_pregao.sqlite3)",
    )
    parser.add_argument(
        "--min-views-ingested-delta",
        type=int,
        default=1,
        help="Delta mínimo de views_ingested_total durante a janela",
    )
    parser.add_argument(
        "--require-route-total-delta",
        action="store_true",
        help="Exige crescimento de route_total durante a janela",
    )

    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=45.0,
        help="Warm-up obrigatório antes da coleta principal",
    )
    parser.add_argument(
        "--warmup-min-ok-samples",
        type=int,
        default=2,
        help="Mínimo de amostras HTTP ok no warm-up",
    )
    parser.add_argument(
        "--warmup-require-route-growth",
        action="store_true",
        help="Exige crescimento de route_total durante warm-up",
    )

    parser.add_argument(
        "--watchdog-consecutive-http-failures",
        type=int,
        default=8,
        help="Aborta tentativa quando atingir N falhas HTTP consecutivas",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Número máximo de tentativas (rerun automático)",
    )
    parser.add_argument(
        "--rerun-backoff-seconds",
        type=float,
        default=8.0,
        help="Espera entre tentativas automáticas",
    )
    parser.add_argument(
        "--disable-rerun-on-health-drop",
        action="store_true",
        help="Desabilita rerun automático quando watchdog detectar queda de health",
    )
    return parser.parse_args()


def _default_out_dir() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path("distributor/logs") / f"m9-rag-operational-evidence-{stamp}"


def _num(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _sqlite_snapshot(path: str, ticker: str, lookback_seconds: int = 300) -> dict[str, Any]:
    out = {
        "sqlite_ok": False,
        "sqlite_exists": False,
        "sqlite_trades_rows": 0,
        "sqlite_walls_rows": 0,
        "sqlite_trade_count_window": 0,
        "sqlite_latest_trade_lag_ms": 0,
    }
    p = Path(path)
    if not p.exists():
        return out
    out["sqlite_exists"] = True
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - max(30, int(lookback_seconds)) * 1000
    try:
        conn = sqlite3.connect(str(p), timeout=1.0)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM rag_trades")
        out["sqlite_trades_rows"] = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM rag_dom_walls")
        out["sqlite_walls_rows"] = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM rag_trades WHERE ticker = ? AND ts_ms >= ?", (ticker, int(cutoff_ms)))
        out["sqlite_trade_count_window"] = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT MAX(ts_ms) FROM rag_trades WHERE ticker = ?", (ticker,))
        max_ts = cur.fetchone()[0]
        out["sqlite_latest_trade_lag_ms"] = max(0, int(now_ms - int(max_ts))) if max_ts else 0
        conn.close()
        out["sqlite_ok"] = True
    except Exception:
        return out
    return out


def _capture_sample(
    *,
    base: str,
    encoded_ticker: str,
    timeout_s: float,
    ticker: str,
    sqlite_path: str,
    phase: str,
    attempt: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ts_epoch_ms": int(time.time() * 1000),
        "ok": False,
        "ticker": ticker,
        "phase": phase,
        "attempt": attempt,
    }
    try:
        health = _request_json(f"{base}/health", timeout_s)
        views = _request_json(f"{base}/api/rag/views?ticker={encoded_ticker}&lookback_seconds=300", timeout_s)
        rag_metrics = health.get("rag_metrics") if isinstance(health.get("rag_metrics"), dict) else {}
        rag_views_status = rag_metrics.get("views") if isinstance(rag_metrics.get("views"), dict) else {}
        row.update(
            {
                "ok": True,
                "ipc_mode": str(health.get("ipc_mode") or ""),
                "route_total": _num(health.get("route_total"), 0),
                "backlog": _num(health.get("backlog"), 0),
                "rag_enabled": bool((health.get("rag_metrics") is not None)),
                "views_ingested_total": _num(rag_metrics.get("views_ingested_total"), 0),
                "vector_store_size": _num(rag_metrics.get("vector_store_size"), 0),
                "views_backend": str(rag_views_status.get("backend") or ""),
                "view_enabled": bool(views.get("enabled")),
                "view_trade_count": _num(views.get("trade_count"), 0),
                "view_trade_qty_sum": _num(views.get("trade_qty_sum"), 0),
                "view_latest_wall_count": _num(views.get("latest_wall_count"), 0),
                "view_wall_count_max": _num(views.get("wall_count_max"), 0),
                "view_has_data": bool(views.get("has_data")),
                "view_lag_ms": _num(views.get("lag_ms"), 0),
            }
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        row["error"] = str(exc)
    if sqlite_path:
        row.update(_sqlite_snapshot(sqlite_path, ticker=ticker, lookback_seconds=300))
    return row


def _write_sample(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=True) + "\n")


def _sqlite_row_healthy(row: dict[str, Any], args: argparse.Namespace) -> bool:
    if not args.sqlite_path:
        return False
    return bool(row.get("sqlite_ok")) and (
        _num(row.get("sqlite_trade_count_window"), 0) > 0
    ) and (
        _num(row.get("sqlite_latest_trade_lag_ms"), int(args.max_lag_ms) + 1) <= int(args.max_lag_ms)
    )


def _evaluate_samples(samples: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    http_failures = sum(1 for s in samples if not bool(s.get("ok")))
    ok_samples = [s for s in samples if bool(s.get("ok"))]
    first_ok = ok_samples[0] if ok_samples else {}
    last_ok = ok_samples[-1] if ok_samples else {}
    views_ingested_delta = _num(last_ok.get("views_ingested_total"), 0) - _num(first_ok.get("views_ingested_total"), 0)
    route_total_delta = _num(last_ok.get("route_total"), 0) - _num(first_ok.get("route_total"), 0)
    max_view_trade_count = max((_num(s.get("view_trade_count"), 0) for s in ok_samples), default=0)
    max_view_wall_count_latest = max((_num(s.get("view_latest_wall_count"), 0) for s in ok_samples), default=0)
    max_view_wall_count_window = max((_num(s.get("view_wall_count_max"), 0) for s in ok_samples), default=0)
    max_view_wall_count = max(max_view_wall_count_latest, max_view_wall_count_window)
    max_lag_seen = max((_num(s.get("view_lag_ms"), 0) for s in ok_samples), default=0)
    any_backend = str(last_ok.get("views_backend") or "")

    checks_http = {
        "http_failures_lte_max": http_failures <= int(args.max_http_failures),
        "ok_samples_gt_0": len(ok_samples) > 0,
        "rag_metrics_visible": bool(ok_samples and all(bool(s.get("rag_enabled")) for s in ok_samples)),
        "views_enabled_visible": bool(ok_samples and any(bool(s.get("view_enabled")) for s in ok_samples)),
        "views_ingested_delta_gte_min": views_ingested_delta >= int(args.min_views_ingested_delta),
        "view_trade_count_gt_0": max_view_trade_count > 0,
        "view_wall_count_gt_0": max_view_wall_count > 0,
        "view_lag_lte_max": (max_lag_seen <= int(args.max_lag_ms)) if ok_samples else False,
    }
    if args.require_route_total_delta:
        checks_http["route_total_delta_gt_0"] = route_total_delta > 0
    if args.expect_views_backend:
        checks_http["views_backend_matches"] = any_backend == str(args.expect_views_backend).strip().lower()

    checks_sqlite: dict[str, bool] = {}
    sqlite_trade_rows_delta = 0
    sqlite_trade_rows_growth = 0
    sqlite_max_window_trade_count = 0
    sqlite_max_walls_rows = 0
    sqlite_max_lag = 0
    sqlite_min_lag = 0

    sqlite_samples = [s for s in samples if bool(s.get("sqlite_ok"))]
    if args.sqlite_path:
        sqlite_first = sqlite_samples[0] if sqlite_samples else {}
        sqlite_last = sqlite_samples[-1] if sqlite_samples else {}
        sqlite_trade_rows_values = [_num(s.get("sqlite_trades_rows"), 0) for s in sqlite_samples]
        sqlite_trade_rows_delta = _num(sqlite_last.get("sqlite_trades_rows"), 0) - _num(
            sqlite_first.get("sqlite_trades_rows"), 0
        )
        sqlite_trade_rows_growth = (
            (max(sqlite_trade_rows_values) - min(sqlite_trade_rows_values)) if sqlite_trade_rows_values else 0
        )
        sqlite_max_window_trade_count = max((_num(s.get("sqlite_trade_count_window"), 0) for s in sqlite_samples), default=0)
        sqlite_max_walls_rows = max((_num(s.get("sqlite_walls_rows"), 0) for s in sqlite_samples), default=0)
        sqlite_max_lag = max((_num(s.get("sqlite_latest_trade_lag_ms"), 0) for s in sqlite_samples), default=0)
        sqlite_min_lag = min((_num(s.get("sqlite_latest_trade_lag_ms"), 0) for s in sqlite_samples), default=0)

        checks_sqlite = {
            "sqlite_samples_gt_0": len(sqlite_samples) > 0,
            "sqlite_trade_rows_growth_gte_min": sqlite_trade_rows_growth >= int(args.min_views_ingested_delta),
            "sqlite_walls_rows_gt_0": sqlite_max_walls_rows > 0,
            "sqlite_trade_count_window_gt_0": sqlite_max_window_trade_count > 0,
            "sqlite_min_lag_lte_max": sqlite_min_lag <= int(args.max_lag_ms),
        }

    http_overall_ok = bool(all(bool(v) for v in checks_http.values()))
    sqlite_overall_ok = bool(checks_sqlite and all(bool(v) for v in checks_sqlite.values()))

    return {
        "http_overall_ok": int(http_overall_ok),
        "sqlite_overall_ok": int(sqlite_overall_ok),
        "http_failures": http_failures,
        "ok_sample_count": len(ok_samples),
        "views_ingested_delta": views_ingested_delta,
        "route_total_delta": route_total_delta,
        "max_view_trade_count": max_view_trade_count,
        "max_view_wall_count": max_view_wall_count,
        "max_view_wall_count_latest": max_view_wall_count_latest,
        "max_view_wall_count_window": max_view_wall_count_window,
        "max_view_lag_ms": max_lag_seen,
        "views_backend_last": any_backend,
        "sqlite_trade_rows_delta": sqlite_trade_rows_delta,
        "sqlite_trade_rows_growth": sqlite_trade_rows_growth,
        "sqlite_max_window_trade_count": sqlite_max_window_trade_count,
        "sqlite_max_walls_rows": sqlite_max_walls_rows,
        "sqlite_max_lag_ms": sqlite_max_lag,
        "sqlite_min_lag_ms": sqlite_min_lag,
        "checks_http": checks_http,
        "checks_sqlite": checks_sqlite,
    }


def _warmup_ready(rows: list[dict[str, Any]], args: argparse.Namespace) -> tuple[bool, dict[str, Any]]:
    ok_rows = [r for r in rows if bool(r.get("ok")) or _sqlite_row_healthy(r, args)]
    http_ok_rows = [r for r in rows if bool(r.get("ok"))]
    route_growth = 0
    if http_ok_rows:
        route_growth = max((_num(r.get("route_total"), 0) for r in http_ok_rows), default=0) - _num(
            http_ok_rows[0].get("route_total"), 0
        )
    checks = {
        "warmup_ok_samples_gte_min": len(ok_rows) >= int(args.warmup_min_ok_samples),
        "warmup_route_growth_gt_0": (route_growth > 0) if args.warmup_require_route_growth else True,
    }
    return bool(all(checks.values())), {"checks": checks, "ok_samples": len(ok_rows), "route_growth": route_growth}


def _run_attempt(
    *,
    args: argparse.Namespace,
    base: str,
    ticker: str,
    encoded_ticker: str,
    timeout_s: float,
    interval_s: float,
    attempt: int,
    attempt_dir: Path,
) -> dict[str, Any]:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    samples_path = attempt_dir / "samples.jsonl"
    warmup_rows: list[dict[str, Any]] = []
    monitor_rows: list[dict[str, Any]] = []

    warmup_deadline = time.time() + max(0.0, float(args.warmup_seconds))
    warmup_ready = False
    warmup_meta: dict[str, Any] = {}
    while time.time() < warmup_deadline:
        row = _capture_sample(
            base=base,
            encoded_ticker=encoded_ticker,
            timeout_s=timeout_s,
            ticker=ticker,
            sqlite_path=args.sqlite_path,
            phase="warmup",
            attempt=attempt,
        )
        warmup_rows.append(row)
        _write_sample(samples_path, row)
        warmup_ready, warmup_meta = _warmup_ready(warmup_rows, args)
        if warmup_ready:
            break
        time.sleep(interval_s)

    if not warmup_ready:
        summary = {
            "attempt": attempt,
            "overall_ok": 0,
            "stop_reason": "warmup_not_ready",
            "warmup": warmup_meta,
            "sample_count": len(warmup_rows),
            "ok_sample_count": sum(1 for r in warmup_rows if bool(r.get("ok"))),
        }
        summary_path = attempt_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
        return summary

    watchdog_threshold = max(1, int(args.watchdog_consecutive_http_failures))
    consecutive_http_failures = 0
    watchdog_triggered = False
    monitor_deadline = time.time() + max(1.0, float(args.duration_seconds))

    while time.time() < monitor_deadline:
        row = _capture_sample(
            base=base,
            encoded_ticker=encoded_ticker,
            timeout_s=timeout_s,
            ticker=ticker,
            sqlite_path=args.sqlite_path,
            phase="monitor",
            attempt=attempt,
        )
        monitor_rows.append(row)
        _write_sample(samples_path, row)

        if bool(row.get("ok")) or _sqlite_row_healthy(row, args):
            consecutive_http_failures = 0
        else:
            consecutive_http_failures += 1
            if consecutive_http_failures >= watchdog_threshold:
                watchdog_triggered = True
                break
        time.sleep(interval_s)

    eval_data = _evaluate_samples(monitor_rows, args)
    overall_ok = int((eval_data["http_overall_ok"] == 1) or (eval_data["sqlite_overall_ok"] == 1))
    if watchdog_triggered:
        overall_ok = 0

    stop_reason = "ok" if overall_ok == 1 else ("watchdog_health_drop" if watchdog_triggered else "gates_failed")
    summary = {
        "attempt": attempt,
        "overall_ok": overall_ok,
        "stop_reason": stop_reason,
        "watchdog_triggered": bool(watchdog_triggered),
        "watchdog_threshold": watchdog_threshold,
        "warmup": warmup_meta,
        "sample_count": len(monitor_rows),
        "duration_seconds": float(args.duration_seconds),
        "interval_seconds": interval_s,
        "timeout_seconds": timeout_s,
        **eval_data,
    }
    summary_path = attempt_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = _parse_args()
    base = args.base_url.rstrip("/")
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    interval_s = max(0.25, float(args.interval_seconds))
    timeout_s = max(0.5, float(args.timeout_seconds))
    ticker = (args.ticker or "WINFUT").strip().upper() or "WINFUT"
    encoded_ticker = urllib.parse.quote(ticker)
    max_attempts = max(1, int(args.max_attempts))
    rerun_on_drop = not bool(args.disable_rerun_on_health_drop)
    backoff_s = max(0.0, float(args.rerun_backoff_seconds))

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        attempt_dir = out_dir / f"attempt-{attempt:02d}"
        result = _run_attempt(
            args=args,
            base=base,
            ticker=ticker,
            encoded_ticker=encoded_ticker,
            timeout_s=timeout_s,
            interval_s=interval_s,
            attempt=attempt,
            attempt_dir=attempt_dir,
        )
        result["summary_path"] = str((attempt_dir / "summary.json"))
        attempts.append(result)

        if int(result.get("overall_ok", 0)) == 1:
            break

        is_drop = str(result.get("stop_reason") or "") in ("watchdog_health_drop", "warmup_not_ready")
        if attempt < max_attempts and rerun_on_drop and is_drop:
            if backoff_s > 0:
                time.sleep(backoff_s)
            continue
        break

    selected = next((a for a in attempts if int(a.get("overall_ok", 0)) == 1), attempts[-1] if attempts else {})
    final_overall_ok = int(selected.get("overall_ok", 0))
    final_summary = {
        "overall_ok": final_overall_ok,
        "base_url": base,
        "ticker": ticker,
        "attempt_count": len(attempts),
        "selected_attempt": int(selected.get("attempt", 0)) if selected else 0,
        "attempts": [
            {
                "attempt": int(a.get("attempt", 0)),
                "overall_ok": int(a.get("overall_ok", 0)),
                "stop_reason": str(a.get("stop_reason", "")),
                "summary_path": str(a.get("summary_path", "")),
            }
            for a in attempts
        ],
    }
    final_summary_path = out_dir / "summary.json"
    final_summary_path.write_text(json.dumps(final_summary, ensure_ascii=True, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "overall_ok": final_overall_ok,
                "summary": str(final_summary_path),
                "selected_attempt": final_summary["selected_attempt"],
            },
            ensure_ascii=True,
        )
    )
    return 0 if final_overall_ok == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
