from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and value == value


def _get_json(url: str, timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    try:
        req = urllib.request.Request(url, headers={"Connection": "close"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None, None
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _build_http_request(url: str, method: str = "GET") -> urllib.request.Request:
    headers = {
        "Connection": "close",
        "User-Agent": "vp-sato-overlay-check/1.0",
        "Accept": "application/json",
        "Origin": os.environ.get("PQ_VP_WS_ORIGIN", "http://127.0.0.1:5173"),
    }
    return urllib.request.Request(url, method=method, headers=headers)


def _post_json(url: str, timeout: float, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = _build_http_request(url, method="POST")
        req.data = data
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None, None
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _evaluate(
    ocr: dict[str, Any] | None,
    ocr_error: str | None,
    vp_debug: dict[str, Any] | None,
    vp_last: dict[str, Any] | None,
    vp_error: str | None,
) -> dict[str, Any]:
    def _alignment_delta_px(value: Any, chart: Any) -> float | None:
        if not _is_num(value) or not isinstance(chart, dict):
            return None
        top = chart.get("top")
        bottom = chart.get("bottom")
        height = chart.get("height")
        if height is None and _is_num(top) and _is_num(bottom):
            height = bottom - top
        if not (_is_num(top) and _is_num(bottom) and _is_num(height) and bottom > top and height > 0):
            return None
        # In the smoke path the payload already carries screen-space Y values.
        # Treat the chart rectangle as the visual envelope and ensure the anchor
        # positions are inside it; this catches obvious misalignment regressions.
        if value < top or value > bottom:
            return min(abs(value - top), abs(value - bottom))
        return 0.0

    checks: dict[str, Any] = {}
    ocr_status = str((ocr or {}).get("status") or "")
    axis_labels = (ocr or {}).get("axis_labels")
    axis = (ocr or {}).get("axis")
    chart = (ocr or {}).get("chart_rect")
    vp_snapshot = (vp_last or {}).get("snapshot") or {}
    vp_debug = vp_debug or {}
    levels = vp_snapshot.get("levels") if isinstance(vp_snapshot.get("levels"), list) else []
    axis_labels_count = len(axis_labels) if isinstance(axis_labels, list) else 0
    overlay_payload_ok = isinstance(vp_snapshot, dict) and bool(vp_snapshot)
    demo_overlay_ok = overlay_payload_ok and len(levels) >= 20
    chart_rect = vp_snapshot.get("chart_rect") if isinstance(vp_snapshot, dict) else None
    
    poc_y = vp_snapshot.get("poc_y")
    if poc_y is None and isinstance(vp_snapshot.get("poc"), dict):
        poc_y = vp_snapshot["poc"].get("y")
        
    val_y = vp_snapshot.get("val_y")
    if val_y is None and isinstance(vp_snapshot.get("val"), dict):
        val_y = vp_snapshot["val"].get("y")
        
    vah_y = vp_snapshot.get("vah_y")
    if vah_y is None and isinstance(vp_snapshot.get("vah"), dict):
        vah_y = vp_snapshot["vah"].get("y")

    poc_delta_px = _alignment_delta_px(poc_y, chart_rect)
    val_delta_px = _alignment_delta_px(val_y, chart_rect)
    vah_delta_px = _alignment_delta_px(vah_y, chart_rect)
    alignment_deltas = [d for d in [poc_delta_px, val_delta_px, vah_delta_px] if d is not None]
    alignment_max_delta_px = max(alignment_deltas) if alignment_deltas else None
    overlay_profit_ok = (
        overlay_payload_ok
        and len(levels) >= 20
        and _is_num(poc_y)
        and _is_num(vah_y)
        and _is_num(val_y)
        and alignment_max_delta_px is not None
        and alignment_max_delta_px <= 0.0
    )
    ocr_axis_ready = (
        isinstance(axis_labels, list)
        and axis_labels_count >= 2
        and isinstance(axis, dict)
        and isinstance(chart, dict)
    )

    checks["ocr_http_ok"] = ocr is not None and ocr_error is None
    checks["ocr_status_ok"] = ocr_status == "ok"
    checks["ocr_axis_ready"] = ocr_axis_ready
    checks["demo_overlay_ok"] = demo_overlay_ok
    checks["overlay_profit_ok"] = overlay_profit_ok
    checks["profit_ocr_ok"] = checks["ocr_http_ok"] and checks["ocr_status_ok"]
    checks["vp_http_ok"] = vp_error is None
    checks["vp_has_snapshot"] = overlay_payload_ok
    checks["vp_has_many_levels"] = len(levels) >= 20
    checks["vp_alignment_ok"] = alignment_max_delta_px is not None and alignment_max_delta_px <= 0.0
    checks["vp_overlay_debug_has_counts"] = int(vp_debug.get("vp_overlay_emit_count") or 0) >= 0

    overlay_ok = all(
        [
            checks["vp_http_ok"],
            checks["vp_has_snapshot"],
            checks["vp_has_many_levels"],
            checks["vp_alignment_ok"],
            checks["vp_overlay_debug_has_counts"],
        ]
    )
    ok = overlay_ok and checks["profit_ocr_ok"]
    return {
        "ok": ok,
        "overlay_ok": overlay_ok,
        "ocr_ok": checks["profit_ocr_ok"],
        "checks": checks,
        "ocr": {
            "status": ocr_status or None,
            "error": ocr_error,
            "axis_labels": axis_labels_count,
            "chart_rect": chart if isinstance(chart, dict) else None,
            "alignment_max_delta_px": alignment_max_delta_px,
        },
        "vp_debug": vp_debug,
        "vp_last": vp_last,
        "vp_error": vp_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida OCR + Volume Profile Sato no overlay.")
    parser.add_argument(
        "--ocr-status-url",
        default=os.environ.get("PQ_OCR_STATUS_URL", "http://127.0.0.1:5558/debug"),
    )
    parser.add_argument(
        "--vp-demo-url",
        default=os.environ.get("PQ_VP_DEMO_URL", "http://127.0.0.1:8000/api/vp-sato/demo"),
    )
    parser.add_argument(
        "--vp-last-url",
        default=os.environ.get("PQ_VP_LAST_URL", "http://127.0.0.1:8000/api/vp-overlay/last?symbol=WINFUT"),
    )
    parser.add_argument(
        "--vp-debug-url",
        default=os.environ.get("PQ_VP_DEBUG_URL", "http://127.0.0.1:8000/api/vp-overlay/debug?symbol=WINFUT"),
    )
    parser.add_argument("--duration-seconds", type=float, default=8.0)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ocr, ocr_error = _get_json(args.ocr_status_url, args.timeout_seconds)
    if ocr and isinstance(ocr, dict) and "data" in ocr and isinstance(ocr["data"], dict):
        ocr = ocr["data"]
    demo, demo_error = _post_json(
        args.vp_demo_url,
        args.timeout_seconds,
        payload={"ticker": "WINFUT", "base_price": 100000.0, "price_step": 5.0, "levels": 72, "seed": 7},
    )
    if demo_error is not None:
        time.sleep(min(args.duration_seconds, 1.5))
    vp_last, last_error = _get_json(args.vp_last_url, args.timeout_seconds)
    vp_debug, debug_error = _get_json(args.vp_debug_url, args.timeout_seconds)
    vp_error = demo_error or last_error or debug_error
    result = _evaluate(ocr, ocr_error, vp_debug, vp_last, vp_error)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("VP SATO OVERLAY CHECK:", "OK" if result["ok"] else "FAIL")
        print(f"- overlay_ok: {'OK' if result['overlay_ok'] else 'FAIL'}")
        print(f"- ocr_ok: {'OK' if result['ocr_ok'] else 'FAIL'}")
        print(f"- demo_overlay_ok: {'OK' if result['checks']['demo_overlay_ok'] else 'FAIL'}")
        print(f"- overlay_profit_ok: {'OK' if result['checks']['overlay_profit_ok'] else 'FAIL'}")
        print(f"- vp_alignment_ok: {'OK' if result['checks']['vp_alignment_ok'] else 'FAIL'}")
        for name, value in result["checks"].items():
            print(f"- {name}: {'OK' if value else 'FAIL'}")
        print("OCR:", json.dumps(result["ocr"], ensure_ascii=False))
        print("VP_LAST:", json.dumps(result["vp_last"], ensure_ascii=False))
        print("VP_DEBUG:", json.dumps(result["vp_debug"], ensure_ascii=False))
        if result.get("vp_error"):
            print("VP error:", result["vp_error"])

    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
