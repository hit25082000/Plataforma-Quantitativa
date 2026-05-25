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
        "event_id": "session_start",
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
    event_ts = _iso_utc_now()
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
                "out_of_bounds": bool(ln.get("out_of_bounds")),
            }
        )
    visible_lines = [ln for ln in rendered_lines if str(ln.get("status") or "").lower() == "visible"]
    out_of_bounds_count = sum(1 for ln in rendered_lines if bool(ln.get("out_of_bounds")))
    return {
        "event": "frame",
        "event_id": "frame",
        "session_id": session_id,
        "seq": int(seq),
        "frame_seq": int(seq),
        "ts": event_ts,
        "timestamp_utc": event_ts,
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
        "render_indicators": {
            "line_count_total": len(rendered_lines),
            "line_count_visible": len(visible_lines),
            "line_count_out_of_bounds": out_of_bounds_count,
        },
        "status_transition": {
            "from": None,
            "to": status,
            "changed": False,
        },
    }


class OcrOverlayAuditTrail:
    def __init__(self, trace_path: str, session_metadata: Dict[str, Any]) -> None:
        self.trace_path = str(Path(trace_path).resolve())
        self.session_metadata = dict(session_metadata)
        if not self.session_metadata.get("event_id") and self.session_metadata.get("event"):
            self.session_metadata["event_id"] = str(self.session_metadata.get("event"))
        if not self.session_metadata.get("started_at"):
            self.session_metadata["started_at"] = _iso_utc_now()
        self._session_header_written = False
        self._last_frame_status: Optional[str] = None

    def _normalize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(record)
        if not normalized.get("event_id") and normalized.get("event"):
            normalized["event_id"] = str(normalized.get("event"))
        if not normalized.get("session_id"):
            normalized["session_id"] = self.session_metadata.get("session_id")
        if not normalized.get("ts"):
            normalized["ts"] = _iso_utc_now()
        if not normalized.get("timestamp_utc"):
            normalized["timestamp_utc"] = normalized["ts"]
        if normalized.get("event") == "frame" and "seq" in normalized and not normalized.get("frame_seq"):
            normalized["frame_seq"] = normalized.get("seq")
        render = normalized.get("render_indicators")
        if not isinstance(render, dict):
            normalized["render_indicators"] = {
                "line_count_total": 0,
                "line_count_visible": 0,
                "line_count_out_of_bounds": 0,
            }
        if normalized.get("event") == "frame":
            current_status = str(normalized.get("status") or "")
            transition = normalized.get("status_transition")
            computed_from = self._last_frame_status
            computed_to = current_status
            computed_changed = bool(computed_from and computed_from != computed_to)
            if isinstance(transition, dict):
                normalized["status_transition"] = {
                    "from": transition.get("from", computed_from),
                    "to": transition.get("to", computed_to),
                    "changed": bool(transition.get("changed", computed_changed)),
                }
            else:
                normalized["status_transition"] = {
                    "from": computed_from,
                    "to": computed_to,
                    "changed": computed_changed,
                }
            self._last_frame_status = current_status or self._last_frame_status
        return normalized

    def append(self, record: Dict[str, Any]) -> None:
        trace_file = Path(self.trace_path)
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        normalized = self._normalize_record(record)
        with trace_file.open("a", encoding="utf-8") as fh:
            if not self._session_header_written:
                fh.write(json.dumps(self.session_metadata, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")
                self._session_header_written = True
            fh.write(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
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
