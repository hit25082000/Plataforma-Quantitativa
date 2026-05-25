from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SESSIONOPS_CONTRACT_VERSION = "v1"
SESSIONOPS_EVENT_TYPES = {
    "session_start",
    "preflight",
    "gate_result",
    "axis_update",
    "overlay_update",
    "ws_health",
    "incident",
    "session_end",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(slots=True)
class SessionContext:
    session_id: str
    run_id: str
    component: str
    build: str
    asset: str
    monitor_dpi: str



def new_session_context(*, component: str, build: str, asset: str = "WINFUT", monitor_dpi: str = "unknown") -> SessionContext:
    return SessionContext(
        session_id=f"sess-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
        run_id=f"run-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
        component=component,
        build=build,
        asset=asset,
        monitor_dpi=monitor_dpi,
    )



def stable_event_id(event: dict[str, Any]) -> str:
    normalized = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()



def validate_event_type(event_type: str) -> str:
    ev = (event_type or "").strip()
    if ev not in SESSIONOPS_EVENT_TYPES:
        raise ValueError(f"invalid_sessionops_event_type: {ev}")
    return ev



def build_event(
    *,
    ctx: SessionContext,
    event_type: str,
    stage: str,
    status: str,
    error_code: str | None = None,
    metrics: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ev = {
        "sessionops_contract_version": SESSIONOPS_CONTRACT_VERSION,
        "event_id": "",
        "event_type": validate_event_type(event_type),
        "session_id": ctx.session_id,
        "run_id": ctx.run_id,
        "component": ctx.component,
        "stage": str(stage or "runtime"),
        "status": str(status or "unknown"),
        "ts_utc": utc_now_iso(),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "build": ctx.build,
        "asset": ctx.asset,
        "monitor_dpi": ctx.monitor_dpi,
        "error_code": error_code or "",
        "metrics": metrics or {},
        "artifacts": artifacts or {},
        "payload": payload or {},
    }
    ev["event_id"] = stable_event_id(ev)
    return ev



def coerce_legacy_ocr_trace_row(row: dict[str, Any], *, default_ctx: SessionContext) -> dict[str, Any]:
    event_kind = str(row.get("event") or "").strip()
    if event_kind == "session_start":
        return build_event(
            ctx=default_ctx,
            event_type="session_start",
            stage="ocr",
            status="started",
            metrics={
                "refresh_ms": row.get("refresh_ms"),
            },
            payload=row,
        )
    status = str(row.get("status") or "unknown")
    return build_event(
        ctx=default_ctx,
        event_type="axis_update",
        stage="ocr",
        status=status,
        metrics={
            "seq": row.get("seq"),
            "labels": len(row.get("labels") or []),
            "residual_px": ((row.get("axis_fit") or {}).get("residual_px") if isinstance(row.get("axis_fit"), dict) else None),
            "confidence": ((row.get("axis_fit") or {}).get("confidence") if isinstance(row.get("axis_fit"), dict) else None),
            "lines": len(row.get("rendered_lines") or []),
        },
        payload=row,
    )
