from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_trace_path() -> str:
    base_dir = Path(__file__).resolve().parent / "logs"
    return str(base_dir / "ocr_overlay_trace.jsonl")


def resolve_trace_path(explicit_path: str = "") -> str:
    chosen = (explicit_path or os.environ.get("PQ_OCR_TRACE_PATH") or "").strip()
    return chosen if chosen else _default_trace_path()


def build_session_metadata(*, session_id: str, symbol: str, refresh_ms: int) -> Dict[str, Any]:
    return {
        "event": "session_start",
        "session_id": session_id,
        "symbol": symbol,
        "refresh_ms": int(refresh_ms),
        "started_at": _iso_utc_now(),
        "pid": os.getpid(),
        "hostname": os.environ.get("COMPUTERNAME") or "",
    }


def build_frame_record(
    *,
    session_id: str,
    seq: int,
    status: str,
    labels: Optional[Iterable[Dict[str, Any]]] = None,
    axis_fit: Optional[Dict[str, Any]] = None,
    axis: Optional[Dict[str, Any]] = None,
    lines: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    axis_fit_obj = axis_fit if isinstance(axis_fit, dict) else {}
    axis_obj = axis if isinstance(axis, dict) else {}
    label_rows: List[Dict[str, Any]] = []
    for lb in labels or ():
        if not isinstance(lb, dict):
            continue
        label_rows.append(
            {
                "value": lb.get("value"),
                "y_screen": lb.get("y_screen"),
            }
        )
    rendered_lines: List[Dict[str, Any]] = []
    for ln in lines or ():
        if not isinstance(ln, dict):
            continue
        rendered_lines.append(
            {
                "label": ln.get("label"),
                "value": ln.get("value"),
                "y_screen": ln.get("y_screen"),
                "status": ln.get("status"),
            }
        )
    return {
        "event": "frame",
        "session_id": session_id,
        "seq": int(seq),
        "ts": _iso_utc_now(),
        "status": status,
        "labels": label_rows,
        "axis_fit": {
            "slope": axis_fit_obj.get("slope"),
            "intercept": axis_fit_obj.get("intercept"),
            "residual_px": axis_fit_obj.get("residual_px"),
            "confidence": axis_fit_obj.get("confidence"),
        },
        "axis_live": {
            "slope": axis_obj.get("slope"),
            "intercept": axis_obj.get("intercept"),
        },
        "rendered_lines": rendered_lines,
    }


class OcrOverlayAuditTrail:
    def __init__(self, trace_path: str, session_metadata: Dict[str, Any]) -> None:
        self.trace_path = str(Path(trace_path).resolve())
        self.session_metadata = dict(session_metadata)
        self._session_header_written = False

    def append(self, record: Dict[str, Any]) -> None:
        trace_file = Path(self.trace_path)
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        with trace_file.open("a", encoding="utf-8") as fh:
            if not self._session_header_written:
                fh.write(json.dumps(self.session_metadata, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")
                self._session_header_written = True
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


def summarize_trace_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    frame_rows = [r for r in rows if str(r.get("event") or "") == "frame"]
    total_frames = len(frame_rows)
    if total_frames == 0:
        return {"total_frames": 0, "ok_frames": 0, "ok_ratio": 0.0, "avg_lines": 0.0}
    ok_frames = sum(1 for r in frame_rows if str(r.get("status") or "") == "ok")
    total_lines = 0
    residual_values: List[float] = []
    confidence_values: List[float] = []
    for frame in frame_rows:
        rendered_lines = frame.get("rendered_lines")
        if isinstance(rendered_lines, list):
            total_lines += len(rendered_lines)
        axis_fit = frame.get("axis_fit")
        if isinstance(axis_fit, dict):
            try:
                residual_values.append(float(axis_fit.get("residual_px")))
            except (TypeError, ValueError):
                pass
            try:
                confidence_values.append(float(axis_fit.get("confidence")))
            except (TypeError, ValueError):
                pass
    return {
        "total_frames": total_frames,
        "ok_frames": ok_frames,
        "ok_ratio": round(ok_frames / total_frames, 4),
        "avg_lines": round(total_lines / total_frames, 3),
        "avg_residual_px": round(sum(residual_values) / len(residual_values), 4) if residual_values else 0.0,
        "avg_confidence": round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0,
    }


def read_trace_window(trace_path: str, window_seconds: int) -> List[Dict[str, Any]]:
    start = time.time() - max(1, int(window_seconds))
    rows: List[Dict[str, Any]] = []
    path = Path(trace_path)
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        ts = str(row.get("ts") or row.get("started_at") or "")
        ts_epoch: Optional[float] = None
        if ts:
            try:
                ts_epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts_epoch = None
        if ts_epoch is None or ts_epoch >= start:
            rows.append(row)
    return rows
