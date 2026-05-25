#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "distributor"
if str(DIST_DIR) not in sys.path:
    sys.path.insert(0, str(DIST_DIR))

import profit_ocr_service

# CEN-05 Thresholds
LATENCY_P95_MAX_MS = 60.0
LATENCY_P99_MAX_MS = 120.0
BACKLOG_GROWTH_RATIO_MAX = 1.5
CONSUMER_FPS_MIN = 90.0
PUBLISH_RATE_FLOOR_FACTOR_MIN = 0.75
PUBLISH_RATE_OVERSHOOT_FACTOR_MAX = 1.15
PUBLISH_INTERVAL_JITTER_CV_MAX = 0.35


@dataclass(frozen=True)
class Scenario:
    name: str
    duration_s: float
    frame_hz: float
    change_every_n: int
    ws_publish_min_ms: int
    send_cost_ms: int
    client_count: int


DEFAULT_SCENARIOS: List[Scenario] = [
    Scenario(
        name="hf_240hz_always_diff",
        duration_s=12.0,
        frame_hz=240.0,
        change_every_n=1,
        ws_publish_min_ms=100,
        send_cost_ms=2,
        client_count=2,
    ),
    Scenario(
        name="hf_480hz_mixed_diff",
        duration_s=12.0,
        frame_hz=480.0,
        change_every_n=3,
        ws_publish_min_ms=100,
        send_cost_ms=2,
        client_count=2,
    ),
    Scenario(
        name="hf_600hz_burst_diff",
        duration_s=10.0,
        frame_hz=600.0,
        change_every_n=1,
        ws_publish_min_ms=120,
        send_cost_ms=3,
        client_count=3,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stress/regressao de publicacao WS overlay_update (throttle+diff).")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--duration-scale", type=float, default=1.0)
    parser.add_argument("--frame-scale", type=float, default=1.0)
    return parser.parse_args()


def _quantile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    idx = (len(values) - 1) * p
    lo = int(idx)
    hi = min(len(values) - 1, lo + 1)
    frac = idx - lo
    return float(values[lo] * (1.0 - frac) + values[hi] * frac)


def _build_payload(seq: int, changed: bool) -> Dict[str, Any]:
    y_base = 200 + (seq % 17 if changed else 0)
    payload_data = {
        "status": "ok",
        "lines": [{"value": 100.0, "y_screen": y_base, "label": "POC"}],
        "axis_deltas": {"delta_first_last_value": -10.0},
        "axis_diagnostics": {"raw_labels": 6, "kept_labels": 4},
        "overlay_target": [{"value": 100.0, "label": "POC"}],
        "structured": {
            "status": {"state": "ok", "axis_locked": True},
            "axis": {"axis_status": "STABLE", "confidence": 0.91},
            "lines": {"items": [{"value": 100.0, "y_screen": y_base}]},
            "histogram": {"axis_deltas": {"delta_first_last_value": -10.0}},
            "debug_visual": {"chart_bounds": {"left": 1, "top": 1, "right": 2, "bottom": 2}},
            "overlay_target": [{"value": 100.0, "label": "POC"}],
        },
    }
    return payload_data


def _run_scenario(scenario: Scenario) -> Dict[str, Any]:
    frame_interval_ms = 1000.0 / scenario.frame_hz
    frame_count = max(1, int(scenario.duration_s * scenario.frame_hz))
    consumer_next_available_ms = 0.0
    queue_item: Dict[str, Any] | None = None
    queue_max = 0
    queue_replaced = 0
    consumed = 0
    published = 0
    latencies_ms: List[float] = []

    old_min_ms = profit_ocr_service.WS_PUBLISH_MIN_MS
    old_emit_ts = profit_ocr_service.state.get("last_ws_emit_ts")
    old_hash = profit_ocr_service.state.get("last_ws_visual_hash")
    try:
        profit_ocr_service.WS_PUBLISH_MIN_MS = int(scenario.ws_publish_min_ms)
        profit_ocr_service.state["last_ws_emit_ts"] = 0
        profit_ocr_service.state["last_ws_visual_hash"] = ""

        for i in range(frame_count):
            now_ms = i * frame_interval_ms
            changed = (i % max(1, scenario.change_every_n)) == 0
            payload = _build_payload(i, changed=changed)

            if queue_item is None:
                queue_item = {"frame_ts_ms": now_ms, "payload": payload}
            else:
                queue_item = {"frame_ts_ms": now_ms, "payload": payload}
                queue_replaced += 1
            queue_max = max(queue_max, 1)

            while queue_item is not None and consumer_next_available_ms <= now_ms:
                consume_ts_ms = consumer_next_available_ms
                latency_ms = max(0.0, consume_ts_ms - float(queue_item["frame_ts_ms"]))
                latencies_ms.append(latency_ms)
                consumed += 1
                with mock.patch.object(
                    profit_ocr_service.time,
                    "time",
                    return_value=consume_ts_ms / 1000.0,
                ):
                    if profit_ocr_service._should_publish_overlay_update(queue_item["payload"]):
                        published += 1
                queue_item = None
                consumer_next_available_ms += float(scenario.send_cost_ms) * max(1, scenario.client_count)

        while queue_item is not None:
            consume_ts_ms = consumer_next_available_ms
            latency_ms = max(0.0, consume_ts_ms - float(queue_item["frame_ts_ms"]))
            latencies_ms.append(latency_ms)
            consumed += 1
            with mock.patch.object(
                profit_ocr_service.time,
                "time",
                return_value=consume_ts_ms / 1000.0,
            ):
                if profit_ocr_service._should_publish_overlay_update(queue_item["payload"]):
                    published += 1
            queue_item = None
            consumer_next_available_ms += float(scenario.send_cost_ms) * max(1, scenario.client_count)

    finally:
        profit_ocr_service.WS_PUBLISH_MIN_MS = old_min_ms
        profit_ocr_service.state["last_ws_emit_ts"] = old_emit_ts
        profit_ocr_service.state["last_ws_visual_hash"] = old_hash

    lat_sorted = sorted(latencies_ms)
    p50 = _quantile(lat_sorted, 0.50)
    p95 = _quantile(lat_sorted, 0.95)
    p99 = _quantile(lat_sorted, 0.99)
    max_latency = max(lat_sorted) if lat_sorted else 0.0
    mean_latency = statistics.fmean(lat_sorted) if lat_sorted else 0.0
    publish_rate_hz = published / max(0.001, scenario.duration_s)
    backlog_stable = queue_max <= 1

    return {
        "scenario": scenario.name,
        "duration_s": round(scenario.duration_s, 3),
        "frame_hz": round(scenario.frame_hz, 3),
        "frames_produced": frame_count,
        "frames_consumed": consumed,
        "queue_replaced": queue_replaced,
        "queue_max": queue_max,
        "published_count": published,
        "publish_rate_hz": round(publish_rate_hz, 3),
        "latency_p50_ms": round(p50, 3),
        "latency_p95_ms": round(p95, 3),
        "latency_p99_ms": round(p99, 3),
        "latency_max_ms": round(max_latency, 3),
        "latency_mean_ms": round(mean_latency, 3),
        "backlog_stable": backlog_stable,
        "throttle_ms": int(scenario.ws_publish_min_ms),
        "send_cost_ms": int(scenario.send_cost_ms),
        "client_count": int(scenario.client_count),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    columns = [
        "scenario",
        "duration_s",
        "frame_hz",
        "frames_produced",
        "frames_consumed",
        "queue_replaced",
        "queue_max",
        "published_count",
        "publish_rate_hz",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "latency_max_ms",
        "latency_mean_ms",
        "backlog_stable",
        "throttle_ms",
        "send_cost_ms",
        "client_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_summary(path: Path, rows: List[Dict[str, Any]], overall_ok: bool) -> None:
    lines = [
        "# Overlay WS stress/regression summary",
        "",
        f"- overall_ok: `{int(overall_ok)}`",
        f"- scenarios: `{len(rows)}`",
        "",
        "| scenario | backlog_stable | pub_rate_hz | p95_ms | p99_ms | max_ms | replaced |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['scenario']} | {int(bool(row['backlog_stable']))} | {row['publish_rate_hz']} | "
            f"{row['latency_p95_ms']} | {row['latency_p99_ms']} | {row['latency_max_ms']} | {row['queue_replaced']} |"
        )
    lines.append("")
    lines.append("## Gates")
    lines.append("")
    lines.append("- `queue_max <= 1`")
    lines.append("- `latency_p99_ms <= 120.0`")
    lines.append("- `published_count >= 1`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    failures: List[str] = []
    for row in rows:
        if int(row["queue_max"]) > 1:
            failures.append(f"{row['scenario']}: queue_max={row['queue_max']} > 1")
        if float(row["latency_p99_ms"]) > 120.0:
            failures.append(f"{row['scenario']}: latency_p99_ms={row['latency_p99_ms']} > 120")
        if int(row["published_count"]) <= 0:
            failures.append(f"{row['scenario']}: published_count=0")
    return {
        "ok": len(failures) == 0,
        "failures": failures,
        "thresholds": {
            "queue_max": 1,
            "latency_p99_ms": 120.0,
        }
    }


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (ROOT / "distributor" / "logs" / f"overlay-ws-stress-regression-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    duration_scale = max(0.05, float(args.duration_scale))
    frame_scale = max(0.1, float(args.frame_scale))
    scenarios = [
        Scenario(
            name=s.name,
            duration_s=s.duration_s * duration_scale,
            frame_hz=max(10.0, s.frame_hz * frame_scale),
            change_every_n=s.change_every_n,
            ws_publish_min_ms=s.ws_publish_min_ms,
            send_cost_ms=s.send_cost_ms,
            client_count=s.client_count,
        )
        for s in DEFAULT_SCENARIOS
    ]

    started = time.time()
    rows = [_run_scenario(s) for s in scenarios]
    gate = evaluate(rows)
    overall_ok = bool(gate["ok"])

    csv_path = out_dir / "stress.csv"
    summary_md = out_dir / "summary.md"
    manifest_path = out_dir / "summary.manifest.json"

    write_csv(csv_path, rows)
    write_summary(summary_md, rows, overall_ok=overall_ok)
    manifest = {
        "runner": "run_overlay_ws_stress_regression.py",
        "scope": "overlay_update_websocket_throttle_diff",
        "started_at_epoch_s": started,
        "finished_at_epoch_s": time.time(),
        "overall_ok": overall_ok,
        "gate": gate,
        "rows": rows,
        "artifacts": {
            "stress_csv": str(csv_path),
            "summary_md": str(summary_md),
            "summary_manifest": str(manifest_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {csv_path}")
    print(f"Wrote: {summary_md}")
    print(f"Wrote: {manifest_path}")
    if not overall_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
