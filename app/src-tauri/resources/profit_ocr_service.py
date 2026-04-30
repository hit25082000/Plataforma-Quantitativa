"""
Serviço OCR para o Overlay do gráfico Profit.

Fonte canónica: distributor/profit_ocr_service.py.
Réplica para o bundle Tauri: scripts/sync-profit-ocr-to-tauri-resources.ps1
(invocado por run-dev.ps1 e build-installer.ps1) → app/src-tauri/resources/.
"""

import asyncio
import contextlib
import json
import math
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

try:
    import ctypes
    from ctypes import wintypes

    import mss
    import pytesseract
    import uvicorn
    import win32gui
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from PIL import Image, ImageEnhance
    from pydantic import BaseModel
except ImportError as e:
    print(f"[OCR] Dependência ausente: {e}")
    print("Execute: pip install -r requirements_ocr.txt")
    sys.exit(1)

from ocr_overlay_audit import (
    OcrOverlayAuditTrail,
    build_frame_record,
    build_session_metadata,
    resolve_trace_path,
)


def _enable_dpi_awareness() -> None:
    """Per-monitor DPI evita desalinhamento entre GetWindowRect (lógico) e captura mss (físico) em 2+ telas."""
    try:
        user32 = ctypes.windll.user32
        ctx = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            if user32.SetProcessDpiAwarenessContext(ctx):
                return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _logical_rect_to_physical(hwnd: int, l: int, t: int, r: int, b: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    if hasattr(user32, "LogicalToPhysicalPoint"):
        pt_lo = wintypes.POINT(l, t)
        pt_hi = wintypes.POINT(r, b)
        user32.LogicalToPhysicalPoint(hwnd, ctypes.byref(pt_lo))
        user32.LogicalToPhysicalPoint(hwnd, ctypes.byref(pt_hi))
        return pt_lo.x, pt_lo.y, pt_hi.x, pt_hi.y
    return l, t, r, b


_enable_dpi_awareness()


def configure_tesseract_cmd() -> None:
    """
    Resolve o executavel do Tesseract sem depender do PATH da sessao.
    Prioriza TESSERACT_CMD e depois caminhos padrao do Windows.
    """
    candidates = []
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd:
        candidates.append(env_cmd)

    candidates.extend(
        [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    )

    for cmd in candidates:
        if os.path.isfile(cmd):
            pytesseract.pytesseract.tesseract_cmd = cmd
            return


# Porta dedicada: 5557 é usada pelo sync_monitor (ZMQ PUB); evitar conflito TCP.
# Sobrescrever com PQ_OCR_PORT (alinhar Tauri + frontend: docs/PORTS.md).
OCR_PORT = int(os.environ.get("PQ_OCR_PORT", "5558"))
try:
    REFRESH_MS = int(os.environ.get("PQ_OCR_REFRESH_MS", "280"))
except ValueError:
    REFRESH_MS = 280
REFRESH_MS = max(120, min(800, REFRESH_MS))
WINDOW_SCAN_INTERVAL_MS = 1200
Y_AXIS_FRAC = 0.14
TOOLBAR_H = int(os.environ.get("PQ_OVERLAY_TOOLBAR_H", "90"))
AXIS_BOTTOM_CROP_PX = int(os.environ.get("PQ_OVERLAY_AXIS_BOTTOM_CROP_PX", "42"))
try:
    MIN_CONF = int(os.environ.get("PQ_OCR_MIN_CONF", "20"))
except ValueError:
    MIN_CONF = 20
# Primeiros segundos: não assustar com "0 labels" enquanto CPU/Tesseract aquecem (PC lento / 1ª captura).
try:
    AXIS_WARMUP_SECS = float(os.environ.get("PQ_OCR_AXIS_WARMUP_SECS", "30"))
except ValueError:
    AXIS_WARMUP_SECS = 30.0
# Suavização das linhas do overlay (0 = desligado; ~0.7 = mais responsivo).
try:
    LINE_Y_SMOOTH_ALPHA = float(os.environ.get("PQ_OVERLAY_LINE_SMOOTH_ALPHA", "0.72"))
except ValueError:
    LINE_Y_SMOOTH_ALPHA = 0.72
# Salto em px entre Y medido e EMA: ignora EMA e “cola” ao valor atual (eixo a convergir).
try:
    LINE_Y_SNAP_PX = float(os.environ.get("PQ_OVERLAY_LINE_Y_SNAP_PX", "22"))
except ValueError:
    LINE_Y_SNAP_PX = 22.0
try:
    AXIS_BLEND_BETA = float(os.environ.get("PQ_OCR_AXIS_BLEND_BETA", "0.52"))
except ValueError:
    AXIS_BLEND_BETA = 0.52
AXIS_BLEND_BETA = min(1.0, max(0.01, AXIS_BLEND_BETA))
COLORS = ["#00FF88", "#FF4444", "#FFB800", "#00CCFF", "#FF88FF", "#FFFFFF"]
LINE_Y_DEADBAND_PX = float(os.environ.get("PQ_OVERLAY_LINE_DEADBAND_PX", "1.5"))
AXIS_MAX_BAD_FRAMES = int(os.environ.get("PQ_OCR_AXIS_MAX_BAD_FRAMES", "8"))
OCR_TRACE_PATH = resolve_trace_path((os.environ.get("PQ_OCR_TRACE_PATH") or "").strip())
OCR_SYMBOL = (os.environ.get("PQ_OCR_SYMBOL") or "WINFUT").strip().upper()
TRACE_SESSION_ID = (os.environ.get("PQ_OCR_TRACE_SESSION_ID") or "").strip() or f"ocr-{int(time.time() * 1000)}"
AXIS_DELTA_SMALL_PX = float(os.environ.get("PQ_OCR_AXIS_DELTA_SMALL_PX", "2.0"))
AXIS_DELTA_MEDIUM_PX = float(os.environ.get("PQ_OCR_AXIS_DELTA_MEDIUM_PX", "8.0"))
AXIS_DELTA_LARGE_PX = float(os.environ.get("PQ_OCR_AXIS_DELTA_LARGE_PX", "20.0"))
AXIS_CONFIRM_SMALL_FRAMES = int(os.environ.get("PQ_OCR_AXIS_CONFIRM_SMALL_FRAMES", "1"))
AXIS_CONFIRM_MEDIUM_FRAMES = int(os.environ.get("PQ_OCR_AXIS_CONFIRM_MEDIUM_FRAMES", "3"))
AXIS_CONFIRM_LARGE_FRAMES = int(os.environ.get("PQ_OCR_AXIS_CONFIRM_LARGE_FRAMES", "8"))
AXIS_MIN_CONFIDENCE = float(os.environ.get("PQ_OCR_AXIS_MIN_CONFIDENCE", "0.45"))
AXIS_MAX_RESIDUAL_PX = float(os.environ.get("PQ_OCR_AXIS_MAX_RESIDUAL_PX", "2.6"))
AXIS_MAX_ERROR_PX = float(os.environ.get("PQ_OCR_AXIS_MAX_ERROR_PX", "6.2"))
try:
    WS_PUBLISH_MIN_MS = int(os.environ.get("PQ_OCR_WS_PUBLISH_MIN_MS", "100"))
except ValueError:
    WS_PUBLISH_MIN_MS = 100
WS_PUBLISH_MIN_MS = max(100, WS_PUBLISH_MIN_MS)
MAX_AXIS_LABELS = max(4, int(os.environ.get("PQ_OCR_MAX_AXIS_LABELS", "18")))
MAX_RENDER_LINES = max(1, int(os.environ.get("PQ_OCR_MAX_RENDER_LINES", "64")))
HISTOGRAM_COMPRESSED_PX = max(1.0, float(os.environ.get("PQ_OCR_HISTOGRAM_COMPRESSED_PX", "4.0")))
HISTOGRAM_COALESCE_Y_PX = max(2.0, float(os.environ.get("PQ_OCR_HISTOGRAM_COALESCE_Y_PX", "4.0")))


def line_color_for_label(label: str, idx: int) -> str:
    """Verde: líder de compra; vermelho: líder de venda; roxo: UBS; demais: paleta."""
    s = (label or "").strip().lower()
    if s == "ubs":
        return "#A855F7"
    if "vendedor" in s or ("venda" in s and "compra" not in s):
        return "#FF4444"
    if "comprador" in s or "compra" in s:
        return "#00FF88"
    return COLORS[idx % len(COLORS)]

state: Dict[str, Any] = {
    "targets": [],
    "positions": [],
    "chart_rect": None,
    "axis_labels": None,
    "axis": None,
    "y_min": None,
    "y_max": None,
    "lines": [],
    "status": "searching",
    "last_update": 0.0,
    "dpi_scale": 1.0,
    # Região opcional só para leitura/verificação (não altera o cálculo das linhas).
    "analysis_roi": None,
    "analysis_sample": None,
    "axis_deltas": None,
    "axis_diagnostics": None,
    "axis_status": "CALIBRATING",
    "axis_source": "none",
    "axis_bad_frames": 0,
    "axis_pending_count": 0,
    "axis_pending_candidate": None,
    "axis_confidence": 0.0,
    "axis_residual_px": 0.0,
    "axis_max_error_px": 0.0,
    "frame_seq": 0,
    "last_frame": None,
    "last_ws_emit_ts": 0.0,
    "last_ws_visual_hash": "",
    "last_render_hash": "",
    "last_render_targets_hash": "",
}
clients: List[WebSocket] = []
service_started_at = time.monotonic()
first_ok_logged = False
ocr_frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
render_frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
AUDIT_TRAIL = OcrOverlayAuditTrail(
    trace_path=OCR_TRACE_PATH,
    session_metadata=build_session_metadata(
        session_id=TRACE_SESSION_ID,
        symbol=OCR_SYMBOL,
        refresh_ms=REFRESH_MS,
    ),
)


def _drop_put_latest(queue: asyncio.Queue, item: Any) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(item)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _axis_status_value() -> str:
    axis_status = str(state.get("axis_status") or "").strip().upper()
    if axis_status:
        return axis_status
    manager_status = str(getattr(axis_manager, "status", "") or "").strip().upper()
    return manager_status or "CALIBRATING"


def _axis_source_value() -> str:
    axis_source = str(state.get("axis_source") or "").strip().lower()
    if axis_source in {"ocr", "manual", "last_stable", "none"}:
        return axis_source
    return "none"


def _reset_axis_quality_metrics() -> None:
    state["axis_confidence"] = 0.0
    state["axis_residual_px"] = 0.0
    state["axis_max_error_px"] = 0.0


def _set_axis_quality_metrics(candidate: Optional[dict[str, Any]]) -> None:
    if not isinstance(candidate, dict):
        _reset_axis_quality_metrics()
        return
    state["axis_confidence"] = float(candidate.get("confidence") or 0.0)
    state["axis_residual_px"] = float(candidate.get("residual_px") or 0.0)
    state["axis_max_error_px"] = float(candidate.get("max_error_px") or 0.0)


def _append_trace_line(record: dict[str, Any]) -> None:
    if not OCR_TRACE_PATH:
        return
    try:
        enriched = dict(record or {})
        if not enriched.get("session_id"):
            enriched["session_id"] = TRACE_SESSION_ID
        if not isinstance(enriched.get("render_indicators"), dict):
            lines = state.get("lines") or []
            visible_lines = [ln for ln in lines if str(ln.get("status") or "").lower() == "visible"]
            out_of_bounds_count = sum(1 for ln in lines if bool(ln.get("out_of_bounds")))
            enriched["render_indicators"] = {
                "line_count_total": len(lines),
                "line_count_visible": len(visible_lines),
                "line_count_out_of_bounds": out_of_bounds_count,
            }
        AUDIT_TRAIL.append(enriched)
    except Exception:
        pass


def _build_frame_debug(
    *,
    seq: int,
    window: Optional[dict[str, Any]],
    chart: Optional[dict[str, Any]],
    labels: List[Dict[str, float]],
    diagnostics: Optional[dict[str, Any]],
    axis_fit: Optional[dict[str, float]],
    axis: Optional[dict[str, float]],
    lines: List[Dict[str, Any]],
    analysis_sample: Optional[Dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    visible_lines = [ln for ln in lines if str(ln.get("status") or "").lower() == "visible"]
    out_of_bounds_count = sum(1 for ln in lines if bool(ln.get("out_of_bounds")))
    chart_bounds = None
    if isinstance(chart, dict):
        chart_bounds = {
            "left": chart.get("left"),
            "top": chart.get("top"),
            "right": (chart.get("left", 0) + chart.get("width", 0)),
            "bottom": (chart.get("top", 0) + chart.get("height", 0)),
            "width": chart.get("width"),
            "height": chart.get("height"),
        }
    return {
        "session_id": TRACE_SESSION_ID,
        "seq": seq,
        "ts": _iso_utc_now(),
        "status": status,
        "window": window,
        "chart_rect": chart,
        "labels_count": len(labels),
        "axis_diagnostics": diagnostics,
        "axis_fit": axis_fit,
        "axis": axis,
        "axis_status": _axis_status_value(),
        "axis_source": _axis_source_value(),
        "bad_frames": axis_manager.bad_frames,
        "pending_count": axis_manager.pending_count,
        "line_count": len(lines),
        "lines": lines,
        "render_indicators": {
            "line_count_total": len(lines),
            "line_count_visible": len(visible_lines),
            "line_count_out_of_bounds": out_of_bounds_count,
            "chart_bounds": chart_bounds,
        },
        "analysis_roi": state.get("analysis_roi"),
        "analysis_sample": analysis_sample,
    }


def _api_ok(endpoint: str, **data: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "endpoint": endpoint,
        "meta": {
            "ts": _iso_utc_now(),
            "status": str(state.get("status") or ""),
            "axis_status": _axis_status_value(),
            "axis_source": _axis_source_value(),
            "frame_seq": int(state.get("frame_seq") or 0),
            "last_update": float(state.get("last_update") or 0.0),
        },
        "data": data,
    }


def _api_error(endpoint: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "endpoint": endpoint,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": {
            "ts": _iso_utc_now(),
            "status": str(state.get("status") or ""),
            "axis_status": _axis_status_value(),
            "axis_source": _axis_source_value(),
            "bad_frames": int(state.get("axis_bad_frames") or 0),
            "pending_count": int(state.get("axis_pending_count") or 0),
            "frame_seq": int(state.get("frame_seq") or 0),
        },
    }


def _normalize_targets(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: "OrderedDict[tuple[float, str], None]" = OrderedDict()
    for target in targets:
        try:
            value = float(target.get("value", 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
        if not math.isfinite(value):
            continue
        label = str(target.get("label") or "").strip()
        deduped[(value, label)] = None
    normalized: List[Dict[str, Any]] = []
    for idx, (value, label) in enumerate(deduped.keys()):
        normalized.append({"id": idx, "value": value, "label": label})
    return normalized


def _build_overlay_update_data() -> dict[str, Any]:
    axis_locked = bool(
        state.get("status") == "ok"
        and isinstance(state.get("axis_labels"), list)
        and len(state.get("axis_labels") or []) >= 2
    )
    targets = _normalize_targets(state.get("targets") or [])
    if len(targets) > MAX_RENDER_LINES:
        targets = targets[:MAX_RENDER_LINES]
    chart_rect = state.get("chart_rect")
    lines_items = state.get("lines") or []
    if len(lines_items) > MAX_RENDER_LINES:
        lines_items = lines_items[:MAX_RENDER_LINES]
    line_block = {
        "items": lines_items,
        "count": len(lines_items),
        "target_count": len(targets),
        "visual_limits": {
            "chart_top": chart_rect.get("top") if isinstance(chart_rect, dict) else None,
            "chart_bottom": (
                chart_rect.get("top", 0) + chart_rect.get("height", 0)
                if isinstance(chart_rect, dict)
                else None
            ),
            "y_min": state.get("y_min"),
            "y_max": state.get("y_max"),
            "max_targets_per_frame": MAX_RENDER_LINES,
            "max_lines_per_frame": MAX_RENDER_LINES,
            "max_axis_labels": MAX_AXIS_LABELS,
        },
    }
    histogram_block = {
        "axis_deltas": state.get("axis_deltas"),
        "axis_diagnostics": state.get("axis_diagnostics"),
    }
    status_block = {
        "state": str(state.get("status") or ""),
        "axis_locked": axis_locked,
        "analysis_roi": state.get("analysis_roi"),
        "analysis_sample": state.get("analysis_sample"),
        "timestamp": state.get("last_update"),
    }
    axis_labels = state.get("axis_labels") if isinstance(state.get("axis_labels"), list) else []
    pending_count = int(state.get("axis_pending_count") or 0)
    axis_source = _axis_source_value()
    axis_block = {
        "axis": state.get("axis"),
        "regression": state.get("axis"),
        "axis_labels": axis_labels,
        "ocr_labels": axis_labels,
        "labels_count": len(axis_labels),
        "axis_status": _axis_status_value(),
        "axis_source": axis_source,
        "source": axis_source,
        "confidence": float(state.get("axis_confidence") or (1.0 if axis_locked else 0.0)),
        "residual_px": float(state.get("axis_residual_px") or 0.0),
        "max_error_px": float(state.get("axis_max_error_px") or 0.0),
        "bad_frames": int(state.get("axis_bad_frames") or 0),
        "pending_count": pending_count,
        "pending_frames": pending_count,
        "pending_candidate": state.get("axis_pending_candidate"),
    }
    debug_visual = {
        "ocr_labels": axis_labels,
        "regression": state.get("axis"),
        "analysis_roi": state.get("analysis_roi"),
        "chart_bounds": {
            "left": chart_rect.get("left") if isinstance(chart_rect, dict) else None,
            "top": chart_rect.get("top") if isinstance(chart_rect, dict) else None,
            "right": (
                chart_rect.get("left", 0) + chart_rect.get("width", 0)
                if isinstance(chart_rect, dict)
                else None
            ),
            "bottom": (
                chart_rect.get("top", 0) + chart_rect.get("height", 0)
                if isinstance(chart_rect, dict)
                else None
            ),
            "width": chart_rect.get("width") if isinstance(chart_rect, dict) else None,
            "height": chart_rect.get("height") if isinstance(chart_rect, dict) else None,
        },
    }
    structured_block = {
        "status": status_block,
        "axis": axis_block,
        "lines": line_block,
        "histogram": histogram_block,
        "debug_visual": debug_visual,
        "overlay_target": targets,
    }
    return {
        # Contrato legado top-level (consumidores antigos)
        "status": status_block["state"],
        "axis_locked": status_block["axis_locked"],
        "lines": line_block["items"],
        "y_min": line_block["visual_limits"]["y_min"],
        "y_max": line_block["visual_limits"]["y_max"],
        "target_count": line_block["target_count"],
        "line_count": line_block["count"],
        "chart_rect": state.get("chart_rect"),
        "axis_deltas": histogram_block["axis_deltas"],
        "axis_diagnostics": histogram_block["axis_diagnostics"],
        "analysis_roi": status_block["analysis_roi"],
        "analysis_sample": status_block["analysis_sample"],
        "ts": status_block["timestamp"],
        "blocks": structured_block,
        # Contrato estruturado (novo)
        "structured": structured_block,
        # Compatibilidade com contratos anteriores
        "overlay_target": targets,
        "axis_status": axis_block["axis_status"],
        "axis_source": axis_block["axis_source"],
        "source": axis_block["source"],
        "confidence": axis_block["confidence"],
        "residual_px": axis_block["residual_px"],
        "max_error_px": axis_block["max_error_px"],
        "bad_frames": axis_block["bad_frames"],
        "pending_count": axis_block["pending_count"],
        "pending_frames": axis_block["pending_frames"],
        "pending_candidate": axis_block["pending_candidate"],
    }


def _sync_axis_runtime_state(*, source: str) -> None:
    state["axis_status"] = str(axis_manager.status or "CALIBRATING").upper()
    state["axis_source"] = source if source in {"ocr", "manual", "last_stable", "none"} else "none"
    state["axis_bad_frames"] = axis_manager.bad_frames
    state["axis_pending_count"] = axis_manager.pending_count
    state["axis_pending_candidate"] = axis_manager.pending_candidate


def _should_publish_overlay_update(payload_data: dict[str, Any]) -> bool:
    now_ms = int(time.time() * 1000.0)
    structured = payload_data.get("structured") if isinstance(payload_data.get("structured"), dict) else {}
    visual_fingerprint = {
        "status": payload_data.get("status"),
        "lines": payload_data.get("lines"),
        "axis_deltas": payload_data.get("axis_deltas"),
        "axis_diagnostics": payload_data.get("axis_diagnostics"),
        "overlay_target": payload_data.get("overlay_target"),
        "structured": structured,
    }
    payload_hash = json.dumps(visual_fingerprint, sort_keys=True, separators=(",", ":"))
    last_hash = str(state.get("last_ws_visual_hash") or "")
    last_emit_ts = int(state.get("last_ws_emit_ts") or 0)
    has_change = payload_hash != last_hash
    throttle_elapsed = (now_ms - last_emit_ts) >= WS_PUBLISH_MIN_MS
    if has_change and throttle_elapsed:
        state["last_ws_visual_hash"] = payload_hash
        state["last_ws_emit_ts"] = now_ms
        return True
    return False

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    configure_tesseract_cmd()
    state["dpi_scale"] = get_dpi_scale()
    ocr_task = asyncio.create_task(ocr_loop())
    render_task = asyncio.create_task(render_loop())
    publish_task = asyncio.create_task(publish_loop())
    try:
        yield
    finally:
        for task in (ocr_task, render_task, publish_task):
            task.cancel()
        for task in (ocr_task, render_task, publish_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Profit OCR Service", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class OverlayTargetIn(BaseModel):
    value: float
    label: str = ""


class PositionsUpdate(BaseModel):
    """Novos clientes enviam targets; legado envia apenas positions."""

    targets: Optional[List[OverlayTargetIn]] = None
    positions: Optional[List[float]] = None


class AnalysisRoiRect(BaseModel):
    left: int
    top: int
    width: int
    height: int


class AnalysisRoiBody(BaseModel):
    """Retângulo em pixels físicos de ecrã (mss). `rect: null` limpa."""

    rect: Optional[AnalysisRoiRect] = None


class ManualAxisPoint(BaseModel):
    value: float
    y_screen: float


class ManualAxisBody(BaseModel):
    points: List[ManualAxisPoint]


class OcrOverlayConfigUpdateBody(BaseModel):
    refresh_ms: Optional[int] = None
    ws_publish_min_ms: Optional[int] = None
    axis_max_bad_frames: Optional[int] = None
    line_y_smooth_alpha: Optional[float] = None
    line_y_snap_px: Optional[float] = None
    line_y_deadband_px: Optional[float] = None
    axis_blend_beta: Optional[float] = None
    axis_warmup_secs: Optional[float] = None
    min_conf: Optional[int] = None


def _targets_from_ws_message(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = msg.get("targets")
    if isinstance(raw, list) and raw:
        out: List[Dict[str, Any]] = []
        for t in raw:
            if isinstance(t, dict) and "value" in t:
                out.append(
                    {
                        "value": float(t["value"]),
                        "label": str(t.get("label") or ""),
                    }
                )
        return out
    pos = msg.get("positions")
    if isinstance(pos, list):
        return [{"value": float(p), "label": ""} for p in pos]
    return []


def _apply_targets(targets: List[Dict[str, Any]]) -> None:
    state["targets"] = targets
    state["positions"] = [t["value"] for t in targets]
    state["last_render_targets_hash"] = json.dumps(_normalize_targets(targets), sort_keys=True, separators=(",", ":"))


def get_dpi_scale() -> float:
    try:
        user32 = ctypes.windll.user32
        dc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
        user32.ReleaseDC(0, dc)
        return dpi / 96.0
    except Exception:
        return 1.0


def find_profit_window() -> Optional[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def _cb(hwnd: int, _unused: Any):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if "profit" in title or "nelogica" in title:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            l, t, r, b = _logical_rect_to_physical(hwnd, l, t, r, b)
            found.append(
                {
                    "hwnd": hwnd,
                    "title": win32gui.GetWindowText(hwnd),
                    "left": l,
                    "top": t,
                    "right": r,
                    "bottom": b,
                    "width": r - l,
                    "height": b - t,
                }
            )

    win32gui.EnumWindows(_cb, None)
    if not found:
        return None
    return max(found, key=lambda w: w["width"] * w["height"])


def resolve_profit_window(now_monotonic: float) -> Optional[Dict[str, Any]]:
    """Usa cache de hwnd/rect entre ciclos para evitar EnumWindows constante."""
    cached = state.get("window_cache")
    if isinstance(cached, dict):
        hwnd = cached.get("hwnd")
        if isinstance(hwnd, int):
            try:
                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    l, t, r, b = win32gui.GetWindowRect(hwnd)
                    l, t, r, b = _logical_rect_to_physical(hwnd, l, t, r, b)
                    if r > l and b > t:
                        cached["left"] = l
                        cached["top"] = t
                        cached["right"] = r
                        cached["bottom"] = b
                        cached["width"] = r - l
                        cached["height"] = b - t
                        cached["title"] = win32gui.GetWindowText(hwnd)
                        state["window_cache"] = cached
                        return cached
            except Exception:
                state["window_cache"] = None

    last_scan = float(state.get("last_window_scan", 0.0))
    if (now_monotonic - last_scan) * 1000.0 < WINDOW_SCAN_INTERVAL_MS:
        return None

    state["last_window_scan"] = now_monotonic
    window = find_profit_window()
    state["window_cache"] = window
    return window


def capture_region(left: int, top: int, width: int, height: int) -> Image.Image:
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def preprocess(img: Image.Image, threshold: int = 140, contrast: float = 2.5) -> tuple[Image.Image, int]:
    img = img.convert("L")
    scale = 3
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = img.point(lambda x: 0 if x < threshold else 255, "1")
    return img, scale


def parse_number(text: str) -> Optional[float]:
    text = text.strip().replace(" ", "")
    if not text:
        return None
    text = re.sub(r"[^\d.,-]", "", text)
    if not text:
        return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "." in text and "," not in text:
            # BR comum no Profit: 185.240 (pontos) = 185240, nao 185.24
            dot_parts = text.split(".")
            if len(dot_parts) > 1 and all(len(p) == 3 for p in dot_parts[1:]):
                text = "".join(dot_parts)
        elif "," in text:
            text = text.replace(",", ".")
        return float(text)
    except ValueError:
        return None


def _tick_aligned(value: float, tick_size: float) -> bool:
    if tick_size <= 0:
        return True
    scaled = value / tick_size
    return abs(scaled - round(scaled)) <= 1e-6


def parse_price_label(text: str, symbol: str = OCR_SYMBOL) -> Optional[float]:
    """
    Parser conservador de preço por ativo.
    Filtra faixa plausível e aderência ao tick para reduzir falsos positivos de OCR.
    """
    value = parse_number(text)
    if value is None:
        return None
    profiles = {
        "WINFUT": {"min": 50000.0, "max": 500000.0, "tick": 5.0},
        "WDOFUT": {"min": 1000.0, "max": 20000.0, "tick": 0.5},
    }
    profile = profiles.get((symbol or "").upper())
    if profile is None:
        return value
    if value < profile["min"] or value > profile["max"]:
        return None
    if not _tick_aligned(value, float(profile["tick"])):
        return None
    return value


def extract_y_axis(chart: Dict[str, Any]) -> List[Dict[str, float]]:
    ax_w = max(70, int(chart["width"] * Y_AXIS_FRAC))
    left = chart["left"] + chart["width"] - ax_w
    top = chart["top"]
    width = ax_w
    height = max(80, chart["height"] - AXIS_BOTTOM_CROP_PX)

    raw = capture_region(left, top, width, height)

    # Passo 1 rapido; passos extras apenas quando o baseline nao for suficiente.
    passes = [
        {"threshold": 140, "contrast": 2.5, "psm": 6},
        {"threshold": 120, "contrast": 3.0, "psm": 6},
        {"threshold": 165, "contrast": 2.1, "psm": 11},
        # Temas escuros / contraste baixo (outro monitor ou escala de texto)
        {"threshold": 100, "contrast": 3.2, "psm": 6},
        {"threshold": 85, "contrast": 3.5, "psm": 11},
    ]

    labels: List[Dict[str, float]] = []

    def _run_pass(p: Dict[str, float]) -> None:
        proc, scale = preprocess(raw, threshold=p["threshold"], contrast=p["contrast"])
        cfg = f"--psm {p['psm']} --oem 3 -c tessedit_char_whitelist=0123456789.,-+"
        data = pytesseract.image_to_data(proc, config=cfg, output_type=pytesseract.Output.DICT)
        for i, word in enumerate(data["text"]):
            word = word.strip()
            conf = int(data["conf"][i]) if str(data["conf"][i]).strip() else -1
            if conf < MIN_CONF or not word:
                continue
            val = parse_price_label(word)
            if val is None:
                continue
            y_orig = (data["top"][i] + data["height"][i] / 2) / scale
            y_screen = top + y_orig
            labels.append({"value": float(val), "y_screen": float(y_screen)})

    _run_pass(passes[0])
    if len(labels) < 2:
        for p in passes[1:]:
            _run_pass(p)
            if len(labels) >= 2:
                break

    labels.sort(key=lambda x: x["y_screen"])
    deduped: List[Dict[str, float]] = []
    for lb in labels:
        if deduped and abs(lb["y_screen"] - deduped[-1]["y_screen"]) < 6:
            continue
        deduped.append(lb)

    # Remove outliers extremos (ex.: "179500" vindo de "179.500"/"00s").
    if deduped:
        abs_vals = sorted(abs(lb["value"]) for lb in deduped)
        med = abs_vals[len(abs_vals) // 2]
        max_abs_allowed = max(5000.0, med * 20.0 + 50.0)
        if med >= 1000:
            min_abs_allowed = med * 0.2
        else:
            min_abs_allowed = 0.0
        filtered = [
            lb
            for lb in deduped
            if min_abs_allowed <= abs(lb["value"]) <= max_abs_allowed
        ]
    else:
        filtered = []

    return filtered


def value_to_y(value: float, labels: List[Dict[str, float]]) -> Optional[int]:
    if len(labels) < 2:
        return None

    by_val = sorted(labels, key=lambda x: x["value"])
    for i in range(len(by_val) - 1):
        lo, hi = by_val[i], by_val[i + 1]
        if lo["value"] == hi["value"]:
            continue
        if min(lo["value"], hi["value"]) <= value <= max(lo["value"], hi["value"]):
            t = (value - lo["value"]) / (hi["value"] - lo["value"])
            return int(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"]))

    lo, hi = (by_val[0], by_val[1]) if value < by_val[0]["value"] else (by_val[-2], by_val[-1])
    v_range = hi["value"] - lo["value"]
    if abs(v_range) < 1e-9:
        return None
    t = (value - lo["value"]) / v_range
    return int(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"]))


def fit_value_axis(labels: List[Dict[str, float]]) -> Optional[Dict[str, float]]:
    """
    Ajuste robusto value = m*y + b (Theil-Sen simplificado).
    Retorna tambem gap aproximado em valor por pixel.
    """
    if len(labels) < 2:
        return None

    slopes: List[float] = []
    n = len(labels)
    for i in range(n):
        yi = labels[i]["y_screen"]
        vi = labels[i]["value"]
        for j in range(i + 1, n):
            yj = labels[j]["y_screen"]
            vj = labels[j]["value"]
            dy = yj - yi
            if abs(dy) < 5:
                continue
            slopes.append((vj - vi) / dy)

    if not slopes:
        return None

    negative_slopes = sorted(s for s in slopes if s < 0)
    all_slopes = sorted(slopes)
    # Eixo Y do Profit tipicamente decresce com y crescente.
    slope = (
        negative_slopes[len(negative_slopes) // 2]
        if len(negative_slopes) >= max(3, len(all_slopes) // 4)
        else all_slopes[len(all_slopes) // 2]
    )
    if abs(slope) < 1e-9:
        return None

    intercepts = sorted(lb["value"] - slope * lb["y_screen"] for lb in labels)
    intercept = intercepts[len(intercepts) // 2]
    value_per_px = abs(slope)
    if value_per_px < 1e-9:
        return None

    residuals = [abs(lb["value"] - (slope * lb["y_screen"] + intercept)) / value_per_px for lb in labels]
    sorted_res = sorted(residuals)
    p75 = sorted_res[int(len(sorted_res) * 0.75)] if sorted_res else 0.0
    inlier_limit = max(2.5, p75 * 1.8)
    inliers = [lb for lb in labels if abs(lb["value"] - (slope * lb["y_screen"] + intercept)) / value_per_px <= inlier_limit]
    if len(inliers) >= 2:
        ys = [float(lb["y_screen"]) for lb in inliers]
        vs = [float(lb["value"]) for lb in inliers]
        y_mean = sum(ys) / len(ys)
        v_mean = sum(vs) / len(vs)
        den = sum((y - y_mean) ** 2 for y in ys)
        if den > 1e-9:
            slope_refit = sum((y - y_mean) * (v - v_mean) for y, v in zip(ys, vs)) / den
            if abs(slope_refit) > 1e-9:
                slope = slope_refit
                intercept = v_mean - slope * y_mean
                value_per_px = abs(slope)
                inliers = [lb for lb in labels if abs(lb["value"] - (slope * lb["y_screen"] + intercept)) / value_per_px <= inlier_limit]

    residual_px = 0.0
    max_error_px = 0.0
    if labels:
        errs = [abs(lb["value"] - (slope * lb["y_screen"] + intercept)) / value_per_px for lb in labels]
        residual_px = sum(errs) / len(errs)
        max_error_px = max(errs)
    confidence = max(0.0, min(1.0, (len(inliers) / max(1, len(labels))) * (1.0 / (1.0 + residual_px + max_error_px * 0.2))))
    return {
        "slope": slope,
        "intercept": intercept,
        "value_per_px": value_per_px,
        "residual_px": residual_px,
        "max_error_px": max_error_px,
        "confidence": confidence,
        "inliers_count": len(inliers),
    }


def sanitize_axis_labels(labels: List[Dict[str, float]], symbol: str = OCR_SYMBOL) -> tuple[List[Dict[str, float]], Dict[str, Any]]:
    """
    Mantém labels coerentes com um eixo de preço monotónico.
    1) monotonicidade (y crescente -> value decrescente)
    2) rejeição de outlier por value/px via mediana + MAD
    """
    if len(labels) < 2:
        return labels, {"raw_labels": len(labels), "kept_labels": len(labels), "rejected": 0}

    by_y = sorted(labels, key=lambda x: x["y_screen"])
    tick_size = 0.0
    if (symbol or "").upper() == "WINFUT":
        tick_size = 5.0
    elif (symbol or "").upper() == "WDOFUT":
        tick_size = 0.5

    deduped: List[Dict[str, float]] = []
    dedupe_rejects = 0
    for lb in by_y:
        if deduped and abs(lb["y_screen"] - deduped[-1]["y_screen"]) < 4:
            dedupe_rejects += 1
            continue
        if tick_size > 0 and not _tick_aligned(float(lb["value"]), tick_size):
            dedupe_rejects += 1
            continue
        deduped.append(lb)

    if len(deduped) < 2:
        return deduped, {
            "raw_labels": len(labels),
            "kept_labels": len(deduped),
            "rejected": len(labels) - len(deduped),
            "rejected_dedupe_or_tick": dedupe_rejects,
        }

    kept = [deduped[0]]
    monotonic_rejects = 0
    for lb in deduped[1:]:
        prev = kept[-1]
        dy = lb["y_screen"] - prev["y_screen"]
        dv = lb["value"] - prev["value"]
        if dy <= 2:
            monotonic_rejects += 1
            continue
        if dv >= 0:
            monotonic_rejects += 1
            continue
        kept.append(lb)

    if len(kept) < 2:
        return deduped[:2], {
            "raw_labels": len(labels),
            "kept_labels": min(2, len(deduped)),
            "rejected": len(labels) - min(2, len(deduped)),
            "rejected_dedupe_or_tick": dedupe_rejects,
            "rejected_monotonic": monotonic_rejects,
            "rejected_slope_outlier": 0,
        }

    seg_slopes: List[float] = []
    for i in range(1, len(kept)):
        dy = kept[i]["y_screen"] - kept[i - 1]["y_screen"]
        dv = kept[i]["value"] - kept[i - 1]["value"]
        if dy > 0 and dv < 0:
            seg_slopes.append(abs(dv / dy))

    if not seg_slopes:
        return kept, {
            "raw_labels": len(labels),
            "kept_labels": len(kept),
            "rejected": len(labels) - len(kept),
            "rejected_dedupe_or_tick": dedupe_rejects,
            "rejected_monotonic": monotonic_rejects,
            "rejected_slope_outlier": 0,
        }

    sorted_slopes = sorted(seg_slopes)
    median = sorted_slopes[len(sorted_slopes) // 2]
    deviations = sorted(abs(x - median) for x in sorted_slopes)
    mad = deviations[len(deviations) // 2]
    tolerance = max(0.02, mad * 2.8, median * 0.35)

    filtered = [kept[0]]
    slope_rejects = 0
    for i in range(1, len(kept)):
        prev = filtered[-1]
        cur = kept[i]
        dy = cur["y_screen"] - prev["y_screen"]
        dv = cur["value"] - prev["value"]
        if dy <= 0 or dv >= 0:
            slope_rejects += 1
            continue
        slope = abs(dv / dy)
        if abs(slope - median) > tolerance:
            slope_rejects += 1
            continue
        filtered.append(cur)

    if len(filtered) < 2:
        filtered = kept[:2]

    return filtered, {
        "raw_labels": len(labels),
        "kept_labels": len(filtered),
        "rejected": len(labels) - len(filtered),
        "rejected_dedupe_or_tick": dedupe_rejects,
        "rejected_monotonic": monotonic_rejects,
        "rejected_slope_outlier": slope_rejects,
        "segment_slope_median": median,
        "segment_slope_mad": mad,
    }


def build_axis_candidate(labels: List[Dict[str, float]], diagnostics: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    fit = fit_value_axis(labels)
    if fit is None:
        return None
    vals = [float(lb["value"]) for lb in labels]
    ys = [float(lb["y_screen"]) for lb in labels]
    return {
        "slope": float(fit["slope"]),
        "intercept": float(fit["intercept"]),
        "value_per_px": float(fit["value_per_px"]),
        "residual_px": float(fit.get("residual_px", 0.0)),
        "max_error_px": float(fit.get("max_error_px", 0.0)),
        "confidence": float(fit.get("confidence", 0.0)),
        "labels_count": len(labels),
        "inliers_count": int(fit.get("inliers_count", 0)),
        "tick_size": 5.0 if OCR_SYMBOL == "WINFUT" else (0.5 if OCR_SYMBOL == "WDOFUT" else 0.0),
        "rejected_dedupe_or_tick": int((diagnostics or {}).get("rejected_dedupe_or_tick", 0) or 0),
        "rejected_monotonic": int((diagnostics or {}).get("rejected_monotonic", 0) or 0),
        "tick_valid": bool((diagnostics or {}).get("rejected_dedupe_or_tick", 0) == 0),
        "monotonic_valid": bool((diagnostics or {}).get("rejected_monotonic", 0) == 0),
        "value_min": min(vals) if vals else None,
        "value_max": max(vals) if vals else None,
        "y_min": min(ys) if ys else None,
        "y_max": max(ys) if ys else None,
    }


def axis_delta_px(candidate: Dict[str, Any], last_stable: Dict[str, float]) -> float:
    slope_new = float(candidate.get("slope") or 0.0)
    slope_old = float(last_stable.get("slope") or 0.0)
    if abs(slope_new) < 1e-9 or abs(slope_old) < 1e-9:
        return math.inf
    v_mid = (float(candidate.get("value_min") or 0.0) + float(candidate.get("value_max") or 0.0)) / 2.0
    y_new = (v_mid - float(candidate.get("intercept") or 0.0)) / slope_new
    y_old = (v_mid - float(last_stable.get("intercept") or 0.0)) / slope_old
    return abs(y_new - y_old)


def is_candidate_valid(candidate: Dict[str, Any]) -> bool:
    if int(candidate.get("labels_count") or 0) < 2:
        return False
    tick_size = float(candidate.get("tick_size") or 0.0)
    tick_is_applicable = tick_size > 0.0
    tick_valid = bool(candidate.get("tick_valid", True))
    if tick_is_applicable and not tick_valid:
        return False
    monotonic_is_applicable = int(candidate.get("labels_count") or 0) >= 3
    monotonic_valid = bool(candidate.get("monotonic_valid", True))
    if monotonic_is_applicable and not monotonic_valid:
        return False
    if float(candidate.get("confidence") or 0.0) < AXIS_MIN_CONFIDENCE:
        return False
    if float(candidate.get("residual_px") or 0.0) > AXIS_MAX_RESIDUAL_PX:
        return False
    if float(candidate.get("max_error_px") or 0.0) > AXIS_MAX_ERROR_PX:
        return False
    return True


def _build_status_light_data() -> dict[str, Any]:
    return {
        "status": str(state.get("status") or ""),
        "axis_status": _axis_status_value(),
        "axis_source": _axis_source_value(),
        "bad_frames": int(state.get("axis_bad_frames") or 0),
        "pending_count": int(state.get("axis_pending_count") or 0),
        "confidence": float(state.get("axis_confidence") or 0.0),
        "residual_px": float(state.get("axis_residual_px") or 0.0),
        "max_error_px": float(state.get("axis_max_error_px") or 0.0),
        "frame_seq": int(state.get("frame_seq") or 0),
        "lines_count": len(state.get("lines") or []),
        "targets_count": len(state.get("targets") or []),
        "last_update": float(state.get("last_update") or 0.0),
        "uptime_sec": round(time.monotonic() - service_started_at, 3),
    }


def compute_axis_deltas(labels: List[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    if len(labels) < 2:
        return None
    by_y = sorted(labels, key=lambda x: x["y_screen"])
    first = by_y[0]
    last = by_y[-1]
    intervals: List[Dict[str, float]] = []
    for i in range(1, len(by_y)):
        prev = by_y[i - 1]
        cur = by_y[i]
        value_delta = float(cur["value"] - prev["value"])
        y_delta = float(cur["y_screen"] - prev["y_screen"])
        value_per_px_segment = abs(value_delta / y_delta) if abs(y_delta) > 1e-9 else math.inf
        intervals.append(
            {
                "i": i - 1,
                "value_delta": value_delta,
                "y_delta": y_delta,
                "value_per_px_segment": value_per_px_segment,
            }
        )
    coalesced_intervals = intervals
    compressed_scale = False
    if intervals:
        mean_abs_y_delta = sum(abs(float(it["y_delta"])) for it in intervals) / len(intervals)
        compressed_scale = mean_abs_y_delta <= HISTOGRAM_COMPRESSED_PX
        if compressed_scale:
            coalesced_intervals = []
            bucket: Dict[str, float] = {"i": 0.0, "value_delta": 0.0, "y_delta": 0.0}
            bucket_first = 0
            for idx, interval in enumerate(intervals):
                if bucket["y_delta"] == 0.0:
                    bucket_first = idx
                bucket["value_delta"] += float(interval["value_delta"])
                bucket["y_delta"] += float(interval["y_delta"])
                if abs(bucket["y_delta"]) >= HISTOGRAM_COALESCE_Y_PX or idx == len(intervals) - 1:
                    y_delta = float(bucket["y_delta"])
                    coalesced_intervals.append(
                        {
                            "i": bucket_first,
                            "value_delta": float(bucket["value_delta"]),
                            "y_delta": y_delta,
                            "value_per_px_segment": abs(float(bucket["value_delta"]) / y_delta) if abs(y_delta) > 1e-9 else math.inf,
                        }
                    )
                    bucket = {"i": 0.0, "value_delta": 0.0, "y_delta": 0.0}
    return {
        "delta_first_last_value": float(last["value"] - first["value"]),
        "delta_first_last_y": float(last["y_screen"] - first["y_screen"]),
        "delta_intervals": intervals,
        "delta_intervals_coalesced": coalesced_intervals,
        "labels_count": len(by_y),
        "compressed_scale": compressed_scale,
    }


def blend_axis_with_hysteresis(new_axis: Dict[str, float]) -> Dict[str, float]:
    prev = state.get("_axis_ema")
    if not isinstance(prev, dict):
        state["_axis_ema"] = new_axis
        state["_axis_jump_count"] = 0
        return new_axis

    prev_slope = float(prev.get("slope", 0.0))
    prev_intercept = float(prev.get("intercept", 0.0))
    slope_rel_jump = abs(new_axis["slope"] - prev_slope) / max(abs(prev_slope), 1e-9)
    intercept_jump = abs(new_axis["intercept"] - prev_intercept)
    jump_limit = max(6.0, float(prev.get("value_per_px", 0.0)) * 8.0)
    jump_detected = slope_rel_jump > 0.10 or intercept_jump > jump_limit

    if jump_detected:
        state["_axis_jump_count"] = int(state.get("_axis_jump_count", 0)) + 1
        beta = min(0.14, AXIS_BLEND_BETA)
    else:
        state["_axis_jump_count"] = 0
        beta = AXIS_BLEND_BETA

    blended = {
        "slope": prev_slope * (1.0 - beta) + new_axis["slope"] * beta,
        "intercept": prev_intercept * (1.0 - beta) + new_axis["intercept"] * beta,
    }
    blended["value_per_px"] = abs(blended["slope"])
    state["_axis_ema"] = blended
    return blended


class StableAxisManager:
    def __init__(self) -> None:
        self.last_stable_axis: Optional[Dict[str, float]] = None
        self.pending_candidate: Optional[Dict[str, Any]] = None
        self.pending_count = 0
        self.bad_frames = 0
        self.status = "CALIBRATING"
        self.manual_locked = False
        self.frozen = False

    def freeze(self) -> None:
        self.frozen = True
        self.status = "FROZEN"

    def unfreeze(self) -> None:
        self.frozen = False
        self.bad_frames = 0
        self.pending_candidate = None
        self.pending_count = 0
        self.status = "RECALIBRATING" if self.last_stable_axis is not None else "CALIBRATING"

    def set_manual_axis(self, axis: Dict[str, float]) -> Dict[str, float]:
        self.last_stable_axis = axis
        self.pending_candidate = None
        self.pending_count = 0
        self.manual_locked = True
        self.frozen = False
        self.bad_frames = 0
        self.status = "MANUAL_LOCKED"
        return axis

    def clear_manual_axis(self) -> None:
        self.manual_locked = False
        self.bad_frames = 0
        self.pending_candidate = None
        self.pending_count = 0
        self.status = "RECALIBRATING" if self.last_stable_axis is not None else "CALIBRATING"

    def _required_confirm_frames(self, delta_px: float) -> int:
        if delta_px <= AXIS_DELTA_SMALL_PX:
            return max(1, AXIS_CONFIRM_SMALL_FRAMES)
        if delta_px <= AXIS_DELTA_MEDIUM_PX:
            return max(1, AXIS_CONFIRM_MEDIUM_FRAMES)
        if delta_px <= AXIS_DELTA_LARGE_PX:
            return max(1, AXIS_CONFIRM_MEDIUM_FRAMES + 1)
        return max(8, AXIS_CONFIRM_LARGE_FRAMES)

    def feed(self, candidate: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
        if self.manual_locked and self.last_stable_axis is not None:
            self.status = "MANUAL_LOCKED"
            return self.last_stable_axis
        if self.frozen and self.last_stable_axis is not None:
            self.status = "FROZEN"
            return self.last_stable_axis
        if candidate is None or not is_candidate_valid(candidate):
            self.bad_frames += 1
            self.pending_candidate = None
            self.pending_count = 0
            if self.last_stable_axis is not None:
                self.status = "FROZEN" if self.bad_frames >= AXIS_MAX_BAD_FRAMES else "SUSPECT"
                return self.last_stable_axis
            self.status = "CALIBRATING"
            return None
        self.bad_frames = 0
        axis_fit = {
            "slope": float(candidate["slope"]),
            "intercept": float(candidate["intercept"]),
            "value_per_px": float(candidate.get("value_per_px") or abs(float(candidate["slope"]))),
        }
        if self.last_stable_axis is None:
            axis = blend_axis_with_hysteresis(axis_fit)
            self.last_stable_axis = axis
            self.pending_candidate = None
            self.pending_count = 0
            self.status = "STABLE"
            return axis

        delta_px = axis_delta_px(candidate, self.last_stable_axis)
        required = self._required_confirm_frames(delta_px)
        if required <= 1:
            axis = blend_axis_with_hysteresis(axis_fit)
            self.last_stable_axis = axis
            self.pending_candidate = None
            self.pending_count = 0
            self.status = "STABLE"
            return axis

        if self.pending_candidate is None:
            self.pending_candidate = candidate
            self.pending_count = 1
        else:
            pending_delta = axis_delta_px(candidate, self.pending_candidate)
            if pending_delta <= AXIS_DELTA_SMALL_PX:
                self.pending_count += 1
                self.pending_candidate = candidate
            else:
                self.pending_candidate = candidate
                self.pending_count = 1

        if self.pending_count < required:
            self.status = "RECALIBRATING" if self.last_stable_axis is not None else "SUSPECT"
            return self.last_stable_axis

        axis = blend_axis_with_hysteresis(axis_fit)
        self.last_stable_axis = axis
        self.pending_candidate = None
        self.pending_count = 0
        self.status = "STABLE"
        return axis


axis_manager = StableAxisManager()


def _build_axis_from_manual_points(points: List[ManualAxisPoint]) -> Optional[Dict[str, float]]:
    if len(points) < 2:
        return None
    p0 = points[0]
    p1 = points[1]
    dy = float(p1.y_screen) - float(p0.y_screen)
    if abs(dy) < 1e-6:
        return None
    slope = (float(p1.value) - float(p0.value)) / dy
    if abs(slope) < 1e-9:
        return None
    intercept = float(p0.value) - slope * float(p0.y_screen)
    return {"slope": slope, "intercept": intercept, "value_per_px": abs(slope)}


def value_to_y_hybrid(value: float, labels: List[Dict[str, float]], axis: Dict[str, float]) -> int:
    if len(labels) >= 2:
        by_val = sorted(labels, key=lambda x: x["value"])
        for i in range(len(by_val) - 1):
            lo, hi = by_val[i], by_val[i + 1]
            if hi["value"] == lo["value"]:
                continue
            if lo["value"] <= value <= hi["value"]:
                t = (value - lo["value"]) / (hi["value"] - lo["value"])
                return int(round(lo["y_screen"] + t * (hi["y_screen"] - lo["y_screen"])))
    yf = (value - axis["intercept"]) / axis["slope"]
    return int(round(yf))


def extract_analysis_sample(rect: Dict[str, Any]) -> Dict[str, Any]:
    """
    OCR numa região definida pelo utilizador (painéis, legendas, etc.).
    Não participa no ajuste do eixo nem nas posições das linhas do overlay.
    """
    left = int(rect["left"])
    top = int(rect["top"])
    w = max(1, int(rect["width"]))
    h = max(1, int(rect["height"]))
    img = capture_region(left, top, w, h)
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.3)
    cfg = "--psm 6 --oem 3"
    try:
        text = pytesseract.image_to_string(gray, config=cfg).strip()
        err_tex = ""
    except Exception as tex_exc:
        text = ""
        err_tex = str(tex_exc)
    numbers: List[float] = []
    seen: set = set()
    try:
        data = pytesseract.image_to_data(
            gray, config=cfg, output_type=pytesseract.Output.DICT
        )
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            if not word:
                continue
            conf = int(data["conf"][i]) if str(data["conf"][i]).strip() else -1
            if conf < 10:
                continue
            val = parse_number(word)
            if val is None:
                continue
            key = round(val, 4)
            if key not in seen:
                seen.add(key)
                numbers.append(float(val))
    except Exception:
        pass
    out: Dict[str, Any] = {
        "text": text[:4000],
        "numbers": numbers[:80],
        "ts": time.time(),
    }
    if err_tex:
        out["tesseract_error"] = err_tex[:500]
    return out


def apply_line_y_smoothing(
    lines: List[Dict[str, Any]], targets: List[Dict[str, Any]]
) -> None:
    """EMA em y_screen para reduzir jitter; salta EMA se o Y novo divergir muito (eixo OCR a estabilizar)."""
    if LINE_Y_SMOOTH_ALPHA <= 0 or not lines:
        return
    tk = tuple(
        (round(float(t.get("value", 0)), 4), str(t.get("label") or ""))
        for t in targets
    )
    if state.get("_smooth_key") != tk:
        state["_line_y_smooth"] = {}
        state["_smooth_key"] = tk
    ema: Dict[str, float] = state.setdefault("_line_y_smooth", {})
    alpha = min(1.0, max(0.01, LINE_Y_SMOOTH_ALPHA))
    chart = state.get("chart_rect") if isinstance(state.get("chart_rect"), dict) else {}
    ch = float(chart.get("height") or 0)
    snap_px = max(float(LINE_Y_SNAP_PX), (ch * 0.025) if ch > 0 else float(LINE_Y_SNAP_PX))
    deadband_px = max(0.0, LINE_Y_DEADBAND_PX)
    for idx, ln in enumerate(lines):
        y = float(ln["y_screen"])
        line_id = f"{idx}:{str(ln.get('label') or '').strip().lower()}:{round(float(ln.get('value') or 0.0), 4)}"
        prev = ema.get(line_id)
        if prev is None:
            ema[line_id] = y
        elif abs(y - prev) <= deadband_px:
            ema[line_id] = prev
        elif abs(y - prev) >= snap_px:
            ema[line_id] = y
        else:
            ema[line_id] = alpha * y + (1.0 - alpha) * prev
        ln["y_screen"] = int(round(ema[line_id]))


def _build_render_context(frame: Dict[str, Any]) -> Dict[str, Any]:
    chart = frame.get("chart_rect")
    axis = frame.get("axis")
    labels = frame.get("labels") or []
    if not isinstance(chart, dict) or not isinstance(axis, dict) or len(labels) < 2:
        return {"lines": [], "status": frame.get("status", "render_skipped")}
    targets = state.get("targets") or []
    if len(targets) > MAX_RENDER_LINES:
        targets = targets[:MAX_RENDER_LINES]
    vals = [lb["value"] for lb in labels]
    v_axis_min = min(vals)
    v_axis_max = max(vals)
    lines = []
    chart_top = float(chart["top"])
    chart_bottom = float(chart["top"] + chart["height"])
    for idx, t in enumerate(targets):
        pos = float(t["value"])
        y_screen = value_to_y_hybrid(pos, labels, axis)
        # Preço fora do intervalo visível no eixo OCR: não usar y híbrido
        # (oscila com blend_axis_with_hysteresis) + clamp geométrico — fixa na borda
        # estável. Eixo Profit: y cresce para baixo, valor decresce (topo = maior preço).
        if pos > v_axis_max:
            clamped_y = int(round(chart_top))
            oob = True
            line_status = "clamped_top"
        elif pos < v_axis_min:
            clamped_y = int(round(chart_bottom))
            oob = True
            line_status = "clamped_bottom"
        else:
            clamped_y = int(round(max(chart_top, min(float(y_screen), chart_bottom))))
            oob = float(y_screen) != float(clamped_y)
            line_status = "visible" if not oob else (
                "clamped_top" if clamped_y <= int(round(chart_top)) else "clamped_bottom"
            )
        lbl = str(t.get("label") or "")
        lines.append(
            {
                "value": pos,
                "y_screen": clamped_y,
                "color": line_color_for_label(lbl, idx),
                "chart_left": chart.get("left"),
                "chart_right": chart.get("left", 0) + chart.get("width", 0),
                "label": lbl,
                "out_of_bounds": oob,
                "status": line_status,
            }
        )
    apply_line_y_smoothing(lines, targets)
    return {"lines": lines, "status": "ok"}


def _should_skip_render(frame: Dict[str, Any]) -> bool:
    render_fingerprint = json.dumps(
        {
            "status": frame.get("status"),
            "axis_status": frame.get("axis_status"),
            "axis_source": frame.get("axis_source"),
            "axis": frame.get("axis"),
            "chart_rect": frame.get("chart_rect"),
            "labels": frame.get("labels"),
            "targets_hash": state.get("last_render_targets_hash"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if render_fingerprint == str(state.get("last_render_hash") or ""):
        return True
    state["last_render_hash"] = render_fingerprint
    return False


async def ocr_loop():
    global first_ok_logged
    while True:
        state["frame_seq"] = int(state.get("frame_seq") or 0) + 1
        seq = int(state["frame_seq"])
        t0 = time.monotonic()
        frame_debug: dict[str, Any] = {"seq": seq, "ts": _iso_utc_now()}
        frame_ctx: dict[str, Any] = {"seq": seq}
        try:
            window = resolve_profit_window(t0)
            if not window:
                state["status"] = "window_not_found"
                state["lines"] = []
                state["axis_labels"] = None
                state["axis"] = None
            else:
                chart = {
                    "left": window["left"],
                    "top": window["top"] + TOOLBAR_H,
                    "width": window["width"],
                    "height": window["height"] - TOOLBAR_H,
                }
                state["chart_rect"] = chart
                labels_raw = extract_y_axis(chart)
                if len(labels_raw) > MAX_AXIS_LABELS:
                    labels_raw = labels_raw[:MAX_AXIS_LABELS]
                labels, diagnostics = sanitize_axis_labels(labels_raw)
                state["axis_diagnostics"] = diagnostics
                frame_ctx["chart_rect"] = chart
                frame_ctx["labels"] = labels
                frame_debug["window"] = window
                frame_debug["chart_rect"] = chart
                frame_debug["labels"] = labels
                frame_debug["axis_diagnostics"] = diagnostics

                if len(labels) >= 2:
                    state["axis_deltas"] = compute_axis_deltas(labels)
                    axis_candidate = build_axis_candidate(labels, diagnostics)
                    frame_debug["axis_fit"] = axis_candidate
                    axis = axis_manager.feed(axis_candidate)
                    if axis is None:
                        state["status"] = "ocr_axis_fit_failed"
                        state["lines"] = []
                        state["axis_labels"] = None
                        state["axis"] = None
                        _sync_axis_runtime_state(source="none")
                        _reset_axis_quality_metrics()
                    else:
                        state["axis_labels"] = [
                            {"value": float(lb["value"]), "y_screen": float(lb["y_screen"])}
                            for lb in labels
                        ]
                        state["axis"] = {
                            "slope": float(axis["slope"]),
                            "intercept": float(axis["intercept"]),
                            "value_per_px": float(axis.get("value_per_px", abs(float(axis["slope"])))),
                        }
                        _sync_axis_runtime_state(source="ocr")
                        _set_axis_quality_metrics(axis_candidate)
                        vals = [lb["value"] for lb in labels]
                        v_axis_min = min(vals)
                        v_axis_max = max(vals)
                        state["y_min"] = v_axis_min
                        state["y_max"] = v_axis_max
                        state["status"] = "ok"
                        if not first_ok_logged:
                            first_ok_logged = True
                            elapsed_ms = int((time.monotonic() - service_started_at) * 1000)
                            print(f"[overlay-latency] ocr_first_ok elapsed_ms={elapsed_ms}")
                        frame_ctx["axis"] = state.get("axis")
                        frame_ctx["status"] = state["status"]
                else:
                    state["axis_deltas"] = None
                    if axis_manager.last_stable_axis is None:
                        axis_manager.feed(None)
                        state["axis_labels"] = None
                        state["axis"] = None
                        _sync_axis_runtime_state(source="none")
                        _reset_axis_quality_metrics()
                    else:
                        axis = axis_manager.feed(None)
                        state["axis"] = axis
                        _sync_axis_runtime_state(source="last_stable")
                        _reset_axis_quality_metrics()
                    elapsed_svc = time.monotonic() - service_started_at
                    if len(labels) == 0 and elapsed_svc < AXIS_WARMUP_SECS:
                        state["status"] = "ocr_axis_warming"
                    else:
                        state["status"] = f"ocr_insufficient_labels:{len(labels)}"
                    state["lines"] = []
                    frame_ctx["axis"] = state.get("axis")
                    frame_ctx["status"] = state["status"]
        except Exception as exc:
            state["status"] = f"error: {exc}"
            state["lines"] = []
            state["axis_labels"] = None
            state["axis"] = None
            axis_manager.feed(None)
            _sync_axis_runtime_state(source="none")
            _reset_axis_quality_metrics()
            frame_debug["error"] = str(exc)
            frame_ctx["status"] = state["status"]

        state["last_update"] = time.time()

        analysis_sample: Optional[Dict[str, Any]] = None
        roi = state.get("analysis_roi")
        if isinstance(roi, dict) and int(roi.get("width", 0)) >= 4 and int(roi.get("height", 0)) >= 4:
            try:
                analysis_sample = extract_analysis_sample(roi)
            except Exception as analy_exc:
                analysis_sample = {
                    "text": "",
                    "numbers": [],
                    "error": str(analy_exc)[:500],
                    "ts": time.time(),
                }
            state["analysis_sample"] = analysis_sample
        else:
            state["analysis_sample"] = None

        frame_debug["status"] = state["status"]
        frame_debug["axis"] = state.get("axis")
        frame_debug["axis_status"] = state.get("axis_status")
        frame_debug["axis_source"] = state.get("axis_source")
        frame_debug["bad_frames"] = state.get("axis_bad_frames")
        frame_debug["pending_count"] = state.get("axis_pending_count")
        frame_debug["pending_candidate"] = state.get("axis_pending_candidate")
        frame_debug["confidence"] = state.get("axis_confidence")
        frame_debug["residual_px"] = state.get("axis_residual_px")
        frame_debug["max_error_px"] = state.get("axis_max_error_px")
        frame_debug["analysis_sample"] = state.get("analysis_sample")
        frame_debug["lines"] = state.get("lines") or frame_debug.get("lines", [])
        state["last_frame"] = frame_debug
        audit_record = build_frame_record(
            session_id=TRACE_SESSION_ID,
            seq=seq,
            status=str(state.get("status") or ""),
            labels=frame_debug.get("labels"),
            axis_fit=frame_debug.get("axis_fit"),
            axis=state.get("axis"),
            lines=state.get("lines") or frame_debug.get("lines", []),
        )
        _append_trace_line(audit_record)
        frame_ctx["axis_status"] = state.get("axis_status")
        frame_ctx["axis_source"] = state.get("axis_source")
        _drop_put_latest(ocr_frame_queue, frame_ctx)

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, REFRESH_MS / 1000 - elapsed))


async def render_loop():
    while True:
        frame = await ocr_frame_queue.get()
        if _should_skip_render(frame):
            continue
        render = _build_render_context(frame)
        state["lines"] = render["lines"]
        if render.get("status"):
            state["status"] = str(render["status"])
        _drop_put_latest(render_frame_queue, {"status": state.get("status"), "ts": state.get("last_update")})


async def publish_loop():
    while True:
        await render_frame_queue.get()
        if not clients:
            continue
        payload_data = _build_overlay_update_data()
        if not _should_publish_overlay_update(payload_data):
            continue
        payload = json.dumps({"type": "overlay_update", "data": payload_data})
        dead: List[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in clients:
                clients.remove(ws)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    await websocket.send_text(
        json.dumps(
            {
                "type": "overlay_update",
                "data": _build_overlay_update_data(),
            }
        )
    )
    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            if msg.get("type") == "set_positions":
                _apply_targets(_targets_from_ws_message(msg))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in clients:
            clients.remove(websocket)


@app.post("/positions")
async def set_positions(body: PositionsUpdate):
    if body.targets is not None:
        _apply_targets(
            [{"value": t.value, "label": t.label} for t in body.targets]
        )
    elif body.positions is not None:
        _apply_targets(
            [{"value": float(p), "label": ""} for p in body.positions]
        )
    return _api_ok("positions", targets=state["targets"], positions=state["positions"])


@app.post("/analysis_roi")
async def set_analysis_roi(body: AnalysisRoiBody):
    if body.rect is None:
        state["analysis_roi"] = None
        state["analysis_sample"] = None
    else:
        state["analysis_roi"] = {
            "left": int(body.rect.left),
            "top": int(body.rect.top),
            "width": max(1, int(body.rect.width)),
            "height": max(1, int(body.rect.height)),
        }
    return _api_ok("analysis_roi", analysis_roi=state["analysis_roi"])


@app.post("/recalibrate")
async def recalibrate_axis():
    """Invalida EMA do eixo e suavização de Y; próxima leitura reancora ao frame atual."""
    state.pop("_axis_ema", None)
    state.pop("_axis_jump_count", None)
    state.pop("_line_y_smooth", None)
    state.pop("_smooth_key", None)
    axis_manager.last_stable_axis = None
    axis_manager.bad_frames = 0
    axis_manager.clear_manual_axis()
    axis_manager.status = "RECALIBRATING"
    state["axis_pending_count"] = 0
    state["axis_pending_candidate"] = None
    state["axis_confidence"] = 0.0
    state["axis_residual_px"] = 0.0
    state["axis_max_error_px"] = 0.0
    return _api_ok(
        "recalibrate",
        message="axis_and_line_smoothing_reset",
        axis_status=axis_manager.status,
        axis_source=state.get("axis_source"),
        bad_frames=state.get("axis_bad_frames"),
    )


@app.post("/api/ocr-overlay/recalibrate")
async def recalibrate_axis_api():
    return await recalibrate_axis()


@app.post("/freeze")
async def freeze_axis():
    axis_manager.freeze()
    return _api_ok(
        "freeze",
        message="axis_frozen",
        axis_status=axis_manager.status,
        axis_source=state.get("axis_source"),
        bad_frames=state.get("axis_bad_frames"),
    )


@app.post("/api/ocr-overlay/freeze")
async def freeze_axis_api():
    return await freeze_axis()


@app.post("/unfreeze")
async def unfreeze_axis():
    axis_manager.unfreeze()
    return _api_ok(
        "unfreeze",
        message="axis_unfrozen",
        axis_status=axis_manager.status,
        axis_source=state.get("axis_source"),
        bad_frames=state.get("axis_bad_frames"),
    )


@app.post("/api/ocr-overlay/unfreeze")
async def unfreeze_axis_api():
    return await unfreeze_axis()


@app.post("/manual_calibration")
async def manual_calibration(body: ManualAxisBody):
    axis = _build_axis_from_manual_points(body.points)
    if axis is None:
        raw_points = [{"value": float(p.value), "y_screen": float(p.y_screen)} for p in body.points]
        return _api_error(
            "manual_calibration",
            "manual_axis_invalid_points",
            "manual_calibration_requires_two_distinct_points",
            points_count=len(body.points),
            points_preview=raw_points[:2],
        )
    state.pop("_axis_ema", None)
    state.pop("_axis_jump_count", None)
    state.pop("_line_y_smooth", None)
    state.pop("_smooth_key", None)
    axis_manager.set_manual_axis(axis)
    state["axis"] = {
        "slope": float(axis["slope"]),
        "intercept": float(axis["intercept"]),
        "value_per_px": float(axis["value_per_px"]),
    }
    state["axis_status"] = axis_manager.status
    state["axis_source"] = "manual"
    state["axis_bad_frames"] = axis_manager.bad_frames
    state["axis_pending_count"] = axis_manager.pending_count
    state["axis_pending_candidate"] = axis_manager.pending_candidate
    state["axis_confidence"] = 1.0
    state["axis_residual_px"] = 0.0
    state["axis_max_error_px"] = 0.0
    return _api_ok(
        "manual_calibration",
        message="manual_axis_applied",
        axis_status=axis_manager.status,
        axis_source=state.get("axis_source"),
        bad_frames=state.get("axis_bad_frames"),
    )


@app.post("/api/ocr-overlay/manual-calibration")
async def manual_calibration_api(body: ManualAxisBody):
    return await manual_calibration(body)


@app.post("/manual_unlock")
async def manual_unlock_axis():
    state.pop("_axis_ema", None)
    state.pop("_axis_jump_count", None)
    state.pop("_line_y_smooth", None)
    state.pop("_smooth_key", None)
    axis_manager.clear_manual_axis()
    axis_manager.unfreeze()
    state["axis_status"] = axis_manager.status
    state["axis_source"] = "none"
    state["axis_bad_frames"] = axis_manager.bad_frames
    state["axis_pending_count"] = axis_manager.pending_count
    state["axis_pending_candidate"] = axis_manager.pending_candidate
    state["axis_confidence"] = 0.0
    state["axis_residual_px"] = 0.0
    state["axis_max_error_px"] = 0.0
    return _api_ok(
        "manual_unlock",
        message="manual_axis_unlocked",
        axis_status=axis_manager.status,
        axis_source=state.get("axis_source"),
        bad_frames=state.get("axis_bad_frames"),
    )


@app.post("/api/ocr-overlay/manual-unlock")
async def manual_unlock_axis_api():
    return await manual_unlock_axis()


@app.get("/debug")
async def get_debug():
    try:
        overlay_update = _build_overlay_update_data()
        return _api_ok(
            "debug",
            status=state["status"],
            last_frame=state.get("last_frame"),
            axis_status=state.get("axis_status"),
            axis_source=state.get("axis_source"),
            bad_frames=state.get("axis_bad_frames"),
            pending_count=state.get("axis_pending_count"),
            pending_candidate=state.get("axis_pending_candidate"),
            confidence=state.get("axis_confidence"),
            residual_px=state.get("axis_residual_px"),
            max_error_px=state.get("axis_max_error_px"),
            axis=state.get("axis"),
            chart_rect=state.get("chart_rect"),
            axis_labels=state.get("axis_labels"),
            axis_diagnostics=state.get("axis_diagnostics"),
            analysis_roi=state.get("analysis_roi"),
            analysis_sample=state.get("analysis_sample"),
            debug_visual=(overlay_update.get("structured") or {}).get("debug_visual"),
            overlay_update=overlay_update,
        )
    except Exception as exc:
        return _api_error(
            "debug",
            "debug_payload_build_failed",
            "failed_to_build_debug_payload",
            exception=str(exc),
            has_last_frame=state.get("last_frame") is not None,
        )


@app.get("/api/ocr-overlay/debug")
async def get_debug_api():
    return await get_debug()


@app.get("/status")
async def get_status():
    try:
        return _api_ok("status", **_build_status_light_data())
    except Exception as exc:
        return _api_error(
            "status",
            "status_payload_build_failed",
            "failed_to_build_status_payload",
            exception=str(exc),
            targets_count=len(state.get("targets") or []),
            lines_count=len(state.get("lines") or []),
        )


@app.get("/api/ocr-overlay/status")
async def get_status_api():
    return await get_status()


@app.get("/config")
async def get_config():
    return _api_ok(
        "config",
        refresh_ms=REFRESH_MS,
        ws_publish_min_ms=WS_PUBLISH_MIN_MS,
        axis_max_bad_frames=AXIS_MAX_BAD_FRAMES,
        line_y_smooth_alpha=LINE_Y_SMOOTH_ALPHA,
        line_y_snap_px=LINE_Y_SNAP_PX,
        line_y_deadband_px=LINE_Y_DEADBAND_PX,
        axis_blend_beta=AXIS_BLEND_BETA,
        axis_warmup_secs=AXIS_WARMUP_SECS,
        min_conf=MIN_CONF,
    )


@app.post("/config")
async def update_config(body: OcrOverlayConfigUpdateBody):
    global REFRESH_MS, WS_PUBLISH_MIN_MS, AXIS_MAX_BAD_FRAMES, LINE_Y_SMOOTH_ALPHA
    global LINE_Y_SNAP_PX, LINE_Y_DEADBAND_PX, AXIS_BLEND_BETA, AXIS_WARMUP_SECS, MIN_CONF

    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=400,
            detail=_api_error(
                "config",
                "config_payload_empty",
                "config_payload_must_include_at_least_one_field",
            ),
        )

    updates: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "refresh_ms":
            REFRESH_MS = max(120, min(800, int(value)))
            updates[key] = REFRESH_MS
        elif key == "ws_publish_min_ms":
            WS_PUBLISH_MIN_MS = max(100, min(2000, int(value)))
            updates[key] = WS_PUBLISH_MIN_MS
        elif key == "axis_max_bad_frames":
            AXIS_MAX_BAD_FRAMES = max(1, min(120, int(value)))
            updates[key] = AXIS_MAX_BAD_FRAMES
        elif key == "line_y_smooth_alpha":
            LINE_Y_SMOOTH_ALPHA = max(0.0, min(1.0, float(value)))
            updates[key] = LINE_Y_SMOOTH_ALPHA
        elif key == "line_y_snap_px":
            LINE_Y_SNAP_PX = max(1.0, min(200.0, float(value)))
            updates[key] = LINE_Y_SNAP_PX
        elif key == "line_y_deadband_px":
            LINE_Y_DEADBAND_PX = max(0.0, min(20.0, float(value)))
            updates[key] = LINE_Y_DEADBAND_PX
        elif key == "axis_blend_beta":
            AXIS_BLEND_BETA = max(0.01, min(1.0, float(value)))
            updates[key] = AXIS_BLEND_BETA
        elif key == "axis_warmup_secs":
            AXIS_WARMUP_SECS = max(0.0, min(120.0, float(value)))
            updates[key] = AXIS_WARMUP_SECS
        elif key == "min_conf":
            MIN_CONF = max(0, min(100, int(value)))
            updates[key] = MIN_CONF

    return _api_ok(
        "config",
        updated=updates,
        refresh_ms=REFRESH_MS,
        ws_publish_min_ms=WS_PUBLISH_MIN_MS,
        axis_max_bad_frames=AXIS_MAX_BAD_FRAMES,
        line_y_smooth_alpha=LINE_Y_SMOOTH_ALPHA,
        line_y_snap_px=LINE_Y_SNAP_PX,
        line_y_deadband_px=LINE_Y_DEADBAND_PX,
        axis_blend_beta=AXIS_BLEND_BETA,
        axis_warmup_secs=AXIS_WARMUP_SECS,
        min_conf=MIN_CONF,
    )


@app.post("/api/ocr-overlay/config")
async def update_config_api(body: OcrOverlayConfigUpdateBody):
    return await update_config(body)


if __name__ == "__main__":
    configure_tesseract_cmd()
    print(f"[OCR] Iniciando serviço OCR na porta {OCR_PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=OCR_PORT, log_level="warning")
