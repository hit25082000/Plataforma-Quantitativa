#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_json_parse(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _fetch_json(base_url: str, path: str, timeout_sec: float = 5.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    req = urlrequest.Request(url, method="GET")
    started = time.monotonic()
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
            parsed = _safe_json_parse(raw)
            if not isinstance(parsed, dict):
                parsed = {"raw": raw}
            return {
                "ok": True,
                "url": url,
                "status_code": int(resp.status),
                "elapsed_ms": elapsed_ms,
                "payload": parsed,
            }
    except urlerror.HTTPError as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        parsed = _safe_json_parse(body)
        return {
            "ok": False,
            "url": url,
            "status_code": int(exc.code),
            "elapsed_ms": elapsed_ms,
            "payload": parsed if isinstance(parsed, dict) else {"raw": body},
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "payload": None,
            "error": str(exc),
        }


def _parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except Exception:  # noqa: BLE001
        return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke de estabilidade startup/conexão/feed.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = max(10, int(args.duration_seconds))
    interval = max(0.5, float(args.interval_seconds))
    base_url = args.base_url.rstrip("/")

    started_mono = time.monotonic()
    started_utc = _now_utc_iso()
    deadline = started_mono + duration

    samples: list[dict[str, Any]] = []
    health_ok_count = 0
    ready_ok_count = 0
    debug_ok_count = 0
    total_count = 0
    feed_live_seen = False
    max_feed_lag_ms = 0.0
    max_broadcast_queue_depth = 0
    backlog_values: list[int] = []
    ws_clients_max = 0
    errors: list[str] = []

    initial_recv: int | None = None
    initial_sent: int | None = None
    final_recv: int | None = None
    final_sent: int | None = None

    while time.monotonic() < deadline:
        ts_wall = time.time()
        health = _fetch_json(base_url, "/health")
        ready = _fetch_json(base_url, "/ready")
        debug = _fetch_json(base_url, "/debug/status")

        total_count += 1
        if health.get("ok", False):
            health_ok_count += 1
        if ready.get("status_code") == 200 and isinstance(ready.get("payload"), dict) and ready["payload"].get("ready") is True:
            ready_ok_count += 1
        if debug.get("ok", False) and isinstance(debug.get("payload"), dict):
            debug_ok_count += 1

        debug_payload = debug.get("payload") if isinstance(debug.get("payload"), dict) else {}
        ready_payload = ready.get("payload") if isinstance(ready.get("payload"), dict) else {}
        health_payload = health.get("payload") if isinstance(health.get("payload"), dict) else {}

        feed_live = bool(
            ready_payload.get("feed_live") is True
            or debug_payload.get("feed_live") is True
            or health_payload.get("feed_live") is True
        )
        if feed_live:
            feed_live_seen = True

        recv_total = int(debug_payload.get("messages_received_total") or 0)
        sent_total = int(debug_payload.get("messages_sent_total") or 0)
        if initial_recv is None:
            initial_recv = recv_total
            initial_sent = sent_total
        final_recv = recv_total
        final_sent = sent_total

        ws_clients = int(debug_payload.get("ws_clients") or 0)
        ws_clients_max = max(ws_clients_max, ws_clients)

        queue_depth = int(
            debug_payload.get("broadcast_queue_depth")
            or health_payload.get("broadcast_queue_depth")
            or health_payload.get("backlog")
            or 0
        )
        backlog_values.append(queue_depth)
        if queue_depth > max_broadcast_queue_depth:
            max_broadcast_queue_depth = queue_depth

        last_market_event_at = (
            debug_payload.get("last_market_event_at")
            or ready_payload.get("last_market_event_at")
            or health_payload.get("last_market_event_at")
        )
        last_market_ts = _parse_iso(last_market_event_at)
        if last_market_ts is not None:
            lag_ms = max(0.0, (ts_wall - last_market_ts) * 1000.0)
            if lag_ms > max_feed_lag_ms:
                max_feed_lag_ms = lag_ms

        if not health.get("ok", False):
            errors.append(f"health_unavailable sample={total_count} err={health.get('error')}")
        if ready.get("status_code") not in (200, 503):
            errors.append(f"ready_unexpected_status sample={total_count} status={ready.get('status_code')}")
        if not debug.get("ok", False):
            errors.append(f"debug_unavailable sample={total_count} err={debug.get('error')}")

        samples.append(
            {
                "ts_utc": _now_utc_iso(),
                "health": health,
                "ready": ready,
                "debug_status": debug,
                "feed_live": feed_live,
                "ws_clients": ws_clients,
                "queue_depth": queue_depth,
            }
        )
        time.sleep(interval)

    health_ok_rate = (health_ok_count / total_count) if total_count else 0.0
    ready_ok_rate = (ready_ok_count / total_count) if total_count else 0.0
    recv_delta = max(0, (final_recv or 0) - (initial_recv or 0))
    sent_delta = max(0, (final_sent or 0) - (initial_sent or 0))

    root_symptom: str | None = None
    next_action: str | None = None

    backlog_growing = False
    if len(backlog_values) >= 6:
        head = backlog_values[: max(2, len(backlog_values) // 2)]
        tail = backlog_values[max(2, len(backlog_values) // 2) :]
        head_avg = sum(head) / len(head)
        tail_avg = sum(tail) / len(tail)
        backlog_growing = tail_avg > head_avg + 2 and max_broadcast_queue_depth > 5

    overall_ok = True
    if health_ok_rate < 0.95:
        overall_ok = False
        root_symptom = "health_instability"
        next_action = "Inspecionar lifecycle do distributor e conflitos de porta 8000."
    elif ready_ok_rate < 0.80:
        overall_ok = False
        root_symptom = "readiness_instability"
        next_action = "Inspecionar bootstrap/consumers e estado /ready."
    elif debug_ok_count == 0:
        overall_ok = False
        root_symptom = "debug_status_unavailable"
        next_action = "Garantir /debug/status e tasks de métricas no distributor."
    elif ws_clients_max > 0 and recv_delta > 0 and sent_delta == 0:
        overall_ok = False
        root_symptom = "websocket_broadcast_stalled"
        next_action = "Inspecionar broadcast WS, queue depth e dropped messages."
    elif backlog_growing:
        overall_ok = False
        root_symptom = "broadcast_backlog_growth"
        next_action = "Ajustar backpressure/coalescing para evitar fila crescente."

    summary = {
        "overall_ok": bool(overall_ok),
        "health_ok_rate": round(health_ok_rate, 4),
        "ready_ok_rate": round(ready_ok_rate, 4),
        "feed_live_seen": bool(feed_live_seen),
        "messages_received_delta": int(recv_delta),
        "messages_sent_delta": int(sent_delta),
        "max_feed_lag_ms": round(max_feed_lag_ms, 2),
        "max_broadcast_queue_depth": int(max_broadcast_queue_depth),
        "root_symptom": root_symptom,
        "next_action": next_action,
        "samples_total": int(total_count),
        "duration_seconds": duration,
        "interval_seconds": interval,
        "ws_clients_max": ws_clients_max,
        "errors_count": len(errors),
    }

    meta = {
        "ts_utc_start": started_utc,
        "ts_utc_end": _now_utc_iso(),
        "hostname": socket.gethostname(),
        "cwd": str(Path.cwd()),
        "base_url": base_url,
    }

    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "samples.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"evidence_written={out_dir}")
    print(
        "overall_ok={ok} health_ok_rate={h:.3f} ready_ok_rate={r:.3f} "
        "recv_delta={rd} sent_delta={sd} max_queue_depth={qd}".format(
            ok=summary["overall_ok"],
            h=summary["health_ok_rate"],
            r=summary["ready_ok_rate"],
            rd=summary["messages_received_delta"],
            sd=summary["messages_sent_delta"],
            qd=summary["max_broadcast_queue_depth"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
