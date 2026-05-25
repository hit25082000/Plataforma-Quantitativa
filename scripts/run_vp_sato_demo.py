from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def _get_json(url: str, timeout: float) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={"Connection": "close"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8", errors="replace"))
        return parsed if isinstance(parsed, dict) else None
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        parsed = json.loads(resp.read().decode("utf-8", errors="replace"))
    return parsed if isinstance(parsed, dict) else {}


def _auto_base_price(ocr_status_url: str, timeout: float, fallback: float) -> float:
    status = _get_json(ocr_status_url, timeout)
    if not status:
        return fallback
    if isinstance(status, dict) and "data" in status and isinstance(status["data"], dict):
        status = status["data"]
    y_min = status.get("y_min")
    y_max = status.get("y_max")
    if isinstance(y_min, (int, float)) and isinstance(y_max, (int, float)) and y_min != y_max:
        return round((float(y_min) + float(y_max)) / 2 / 5) * 5
    return fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Publica um VP Sato sintético para teste fora do pregão.")
    parser.add_argument("--url", default=os.environ.get("PQ_VP_SATO_DEMO_URL", "http://127.0.0.1:8000/api/vp-sato/demo"))
    parser.add_argument("--ocr-status-url", default=os.environ.get("PQ_OCR_STATUS_URL", "http://127.0.0.1:5558/debug"))
    parser.add_argument("--duration-seconds", type=float, default=180.0)
    parser.add_argument("--interval-seconds", type=float, default=0.35)
    parser.add_argument("--ticker", default="DEMO")
    parser.add_argument("--base-price", type=float, default=100000.0)
    parser.add_argument("--price-step", type=float, default=5.0)
    parser.add_argument("--levels", type=int, default=72)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--animate", action="store_true")
    parser.add_argument("--no-auto-base-price", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=2.5)
    args = parser.parse_args()

    base_price = (
        args.base_price
        if args.no_auto_base_price
        else _auto_base_price(args.ocr_status_url, args.timeout_seconds, args.base_price)
    )
    started = time.monotonic()
    sent = 0
    last_response: dict[str, Any] | None = None
    last_error: str | None = None

    print(
        f"VP Sato demo ativo: ticker={args.ticker} base_price={base_price:.0f} "
        f"levels={args.levels} duration={args.duration_seconds:.0f}s "
        f"mode={'animate' if args.animate else 'stable'}"
    )
    print("Abra o overlay. Se aparecer 'fallback', o OCR não está calibrando o eixo agora.")

    while time.monotonic() - started < args.duration_seconds:
        payload = {
            "ticker": args.ticker,
            "base_price": base_price,
            "price_step": args.price_step,
            "levels": args.levels,
            "seed": sent if args.animate else args.seed,
        }
        try:
            last_response = _post_json(args.url, payload, args.timeout_seconds)
            last_error = None
            sent += 1
        except Exception as exc:
            last_error = str(exc)
            break
        time.sleep(max(0.05, args.interval_seconds))

    if last_error:
        print(f"FAIL: {last_error}")
        print("Se o endpoint não existir, reinicie o distributor/app para carregar esta alteração.")
        return 2
    print(json.dumps({"ok": sent > 0, "sent": sent, "last_response": last_response}, ensure_ascii=False))
    return 0 if sent > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
