from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import time
import urllib.error
import urllib.request
from typing import Any


def _http_json(url: str, timeout: float, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Connection": "close",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "vp-sato-performance-evidence/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8", errors="replace"))
        return parsed if isinstance(parsed, dict) else None
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None


async def _publish_demo(
    demo_url: str,
    symbol: str,
    duration: float,
    interval: float,
    base_price: float,
    price_step: float,
    levels: int,
    timeout: float,
) -> int:
    sent = 0
    deadline = time.monotonic() + duration
    seed = 0
    while time.monotonic() < deadline:
        payload = {
            "ticker": symbol,
            "base_price": base_price,
            "price_step": price_step,
            "levels": levels,
            "seed": seed,
        }
        resp = await asyncio.to_thread(_http_json, demo_url, timeout, "POST", payload)
        if resp is not None:
            sent += 1
            seed += 1
        await asyncio.sleep(max(0.05, interval))
    return sent


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
    return values[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidência de performance do overlay VP Sato em fluxo real/replay.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="WINFUT")
    parser.add_argument("--duration-seconds", type=float, default=180.0)
    parser.add_argument("--interval-seconds", type=float, default=0.35)
    parser.add_argument("--warmup-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=4.0)
    parser.add_argument("--levels", type=int, default=72)
    parser.add_argument("--base-price", type=float, default=100000.0)
    parser.add_argument("--price-step", type=float, default=5.0)
    parser.add_argument("--min-route-hz", type=float, default=4.0)
    parser.add_argument("--max-route-hz", type=float, default=10.0)
    parser.add_argument("--max-route-avg-ms", type=float, default=33.0)
    parser.add_argument("--max-dropped", type=int, default=0)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else pathlib.Path("distributor/logs") / f"vp-sato-performance-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    async def _run() -> dict[str, Any]:
        publisher = asyncio.create_task(
            _publish_demo(
                f"{base}/api/vp-overlay/demo",
                args.symbol,
                max(0.0, args.duration_seconds - args.warmup_seconds),
                args.interval_seconds,
                args.base_price,
                args.price_step,
                args.levels,
                args.timeout_seconds,
            )
        )
        await asyncio.sleep(max(0.0, args.warmup_seconds))
        samples: list[dict[str, Any]] = []
        deadline = time.monotonic() + args.duration_seconds
        while time.monotonic() < deadline:
            health = await asyncio.to_thread(_http_json, f"{base}/health", args.timeout_seconds)
            debug = await asyncio.to_thread(_http_json, f"{base}/api/vp-overlay/debug?symbol={args.symbol}", args.timeout_seconds)
            last = await asyncio.to_thread(_http_json, f"{base}/api/vp-overlay/last?symbol={args.symbol}", args.timeout_seconds)
            samples.append({"ts": time.monotonic(), "health": health, "debug": debug, "last": last})
            await asyncio.sleep(1.0)
        sent = await publisher
        return {"sent": sent, "samples": samples}

    result = asyncio.run(_run())

    health_before = _http_json(f"{base}/health", args.timeout_seconds)
    debug_before = _http_json(f"{base}/api/vp-overlay/debug?symbol={args.symbol}", args.timeout_seconds)
    health_after = _http_json(f"{base}/health", args.timeout_seconds)
    debug_after = _http_json(f"{base}/api/vp-overlay/debug?symbol={args.symbol}", args.timeout_seconds)

    samples = result["samples"]
    times = [sample["ts"] for sample in samples]
    route_avg_ms = [
        float(sample["health"]["route_avg_ms"])
        for sample in samples
        if isinstance(sample.get("health"), dict) and isinstance(sample["health"].get("route_avg_ms"), (int, float))
    ]
    dropped = [
        int(sample["health"]["vp_overlay_client_queue_dropped"])
        for sample in samples
        if isinstance(sample.get("health"), dict)
        and isinstance(sample["health"].get("vp_overlay_client_queue_dropped"), (int, float))
    ]
    publish_hz = [
        float(sample["debug"]["consolidator"]["overlay_publish_hz"])
        for sample in samples
        if isinstance(sample.get("debug"), dict)
        and isinstance(sample["debug"].get("consolidator"), dict)
        and isinstance(sample["debug"]["consolidator"].get("overlay_publish_hz"), (int, float))
    ]
    seqs = [
        int(sample["last"]["snapshot"]["sequence"])
        for sample in samples
        if isinstance(sample.get("last"), dict)
        and isinstance(sample["last"].get("snapshot"), dict)
        and isinstance(sample["last"]["snapshot"].get("sequence"), int)
    ]

    duration_observed = max(0.001, (max(times) - min(times)) if len(times) >= 2 else args.duration_seconds)
    sample_hz = len(samples) / duration_observed
    route_avg_p95 = _percentile(route_avg_ms, 0.95)
    publish_hz_avg = statistics.fmean(publish_hz) if publish_hz else None
    max_drop = max(dropped) if dropped else None
    seq_jump = max((b - a) for a, b in zip(seqs, seqs[1:])) if len(seqs) >= 2 else None

    ok = True
    ok = ok and len(samples) > 0
    ok = ok and sample_hz >= args.min_route_hz
    ok = ok and (publish_hz_avg is None or publish_hz_avg <= args.max_route_hz * 1.5)
    ok = ok and (route_avg_p95 is None or route_avg_p95 <= args.max_route_avg_ms)
    ok = ok and (max_drop is None or max_drop <= args.max_dropped)

    summary = {
        "ok": ok,
        "base_url": base,
        "symbol": args.symbol,
        "duration_seconds": args.duration_seconds,
        "warmup_seconds": args.warmup_seconds,
        "sent": result["sent"],
        "sample_count": len(samples),
        "sample_hz": sample_hz,
        "route_avg_ms_p95": route_avg_p95,
        "publish_hz_avg": publish_hz_avg,
        "queue_dropped_max": max_drop,
        "sequence_jump_max": seq_jump,
        "health_before": health_before,
        "health_after": health_after,
        "debug_before": debug_before,
        "debug_after": debug_after,
        "samples": samples[-20:],
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(
        "\n".join(
            [
                "# VP Sato performance evidence",
                "",
                f"- ok: {summary['ok']}",
                f"- sent: {summary['sent']}",
                f"- sample_count: {summary['sample_count']}",
                f"- sample_hz: {summary['sample_hz']:.2f}",
                f"- route_avg_ms_p95: {summary['route_avg_ms_p95']}",
                f"- publish_hz_avg: {summary['publish_hz_avg']}",
                f"- queue_dropped_max: {summary['queue_dropped_max']}",
                f"- sequence_jump_max: {summary['sequence_jump_max']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print((out_dir / "summary.md").read_text(encoding="utf-8"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
