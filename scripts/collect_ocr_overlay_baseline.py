#!/usr/bin/env python
"""Coleta baseline OCR overlay (status/debug/debug-dump) por sessão.

Uso:
python scripts/collect_ocr_overlay_baseline.py --duration-sec 90
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _get_json(url: str, timeout: float = 2.5) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(payload)
    if not isinstance(obj, dict):
        raise ValueError(f"invalid_json_object:{url}")
    return obj


def _post_json(url: str, timeout: float = 15.0) -> dict[str, Any]:
    req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(payload)
    if not isinstance(obj, dict):
        raise ValueError(f"invalid_json_object:{url}")
    return obj


def _extract_record(status: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    s = status.get("data") if isinstance(status.get("data"), dict) else {}
    d = debug.get("data") if isinstance(debug.get("data"), dict) else {}
    return {
        "ts": time.time(),
        "axis_status": s.get("axis_status") or d.get("axis_status"),
        "axis_source": s.get("axis_source") or d.get("axis_source"),
        "confidence": s.get("confidence") or d.get("confidence"),
        "residual_px": s.get("residual_px") or d.get("residual_px"),
        "max_error_px": s.get("max_error_px") or d.get("max_error_px"),
        "bad_frames": s.get("bad_frames") or d.get("bad_frames"),
        "parsed_labels_count": d.get("parsed_labels_count"),
        "overlay_rect_screen_physical": d.get("geometry", {}).get("overlay_rect_screen_physical") if isinstance(d.get("geometry"), dict) else None,
        "chart_rect": d.get("chart_rect"),
        "geometry_consistency": {
            "line_count": len(d.get("overlay_update", {}).get("lines", [])) if isinstance(d.get("overlay_update"), dict) else 0,
            "all_lines_have_y_overlay_css": all(
                isinstance(ln, dict) and isinstance(ln.get("y_overlay_css"), (int, float))
                for ln in ((d.get("overlay_update") or {}).get("lines") or [])
            ) if isinstance(d.get("overlay_update"), dict) else False,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:5558")
    ap.add_argument("--duration-sec", type=int, default=90)
    ap.add_argument("--interval-ms", type=int, default=500)
    ap.add_argument("--out-dir", default="distributor/logs")
    ap.add_argument("--run-debug-dump", action="store_true")
    args = ap.parse_args()

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"ocr-overlay-baseline-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / "baseline.jsonl"

    status_url = f"{args.base_url}/api/ocr-overlay/status"
    debug_url = f"{args.base_url}/api/ocr-overlay/debug"
    dump_url = f"{args.base_url}/api/ocr-overlay/debug-dump"

    started = time.time()
    samples = 0
    failures = 0
    with out_jsonl.open("w", encoding="utf-8") as fh:
        while (time.time() - started) < max(1, args.duration_sec):
            try:
                status = _get_json(status_url)
                debug = _get_json(debug_url)
                rec = _extract_record(status, debug)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                samples += 1
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                failures += 1
                fh.write(json.dumps({"ts": time.time(), "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            time.sleep(max(0.05, args.interval_ms / 1000.0))

    dump_result: dict[str, Any] | None = None
    if args.run_debug_dump:
        try:
            dump_result = _post_json(dump_url)
            (out_dir / "debug_dump_response.json").write_text(
                json.dumps(dump_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            (out_dir / "debug_dump_error.txt").write_text(str(exc), encoding="utf-8")

    summary = {
        "ok": samples > 0,
        "samples": samples,
        "failures": failures,
        "duration_sec": args.duration_sec,
        "interval_ms": args.interval_ms,
        "baseline_jsonl": str(out_jsonl),
        "debug_dump_requested": bool(args.run_debug_dump),
        "debug_dump_ok": bool(dump_result and dump_result.get("ok") is True),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if samples > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
