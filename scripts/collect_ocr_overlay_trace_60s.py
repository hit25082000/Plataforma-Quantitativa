from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "distributor"
if str(DIST) not in sys.path:
    sys.path.insert(0, str(DIST))

from ocr_overlay_audit import read_trace_window, resolve_trace_path, summarize_trace_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta janela OCR/overlay e gera sumario basico.")
    parser.add_argument("--duration-sec", type=int, default=60, help="Duracao de coleta em segundos.")
    parser.add_argument("--trace-path", type=str, default="", help="Caminho do jsonl (opcional).")
    parser.add_argument(
        "--summary-out",
        type=str,
        default="",
        help="Arquivo de saida para sumario JSON (opcional).",
    )
    args = parser.parse_args()

    duration = max(1, int(args.duration_sec))
    trace_path = resolve_trace_path(args.trace_path)
    print(f"[ocr-audit] collecting window: {duration}s trace={trace_path}")
    time.sleep(duration)
    rows = read_trace_window(trace_path, duration)
    summary = summarize_trace_rows(rows)
    payload = {
        "trace_path": trace_path,
        "window_seconds": duration,
        "summary": summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    summary_out = (args.summary_out or "").strip()
    if summary_out:
        out_path = Path(summary_out).resolve()
    else:
        out_path = (ROOT / "distributor" / "logs" / "ocr_overlay_trace.summary.json").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ocr-audit] summary written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
