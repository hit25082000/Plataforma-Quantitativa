from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sessionops_contract import build_event, new_session_context
from sessionops_store import SessionOpsStore

FAILURE_TAXONOMY = {
    "engine_not_started",
    "ocr_no_axis",
    "overlay_ws_stale",
    "dpi_drift_detected",
    "health_unavailable",
    "ready_unavailable",
    "debug_status_unavailable",
    "ocr_status_unavailable",
    "ocr_debug_unavailable",
}


class SessionOpsService:
    def __init__(
        self,
        *,
        logs_root: str | Path,
        component: str,
        build: str,
        default_asset: str = "WINFUT",
    ) -> None:
        self.logs_root = Path(logs_root).resolve()
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self._session_dir_root = self.logs_root / "sessionops"
        self._session_dir_root.mkdir(parents=True, exist_ok=True)
        self._events_jsonl_path = self._session_dir_root / "events.jsonl"
        self._store = SessionOpsStore(self._session_dir_root / "session_registry.db")
        self.ctx = new_session_context(component=component, build=build, asset=default_asset)
        self._ws_health: dict[str, dict[str, Any]] = {
            "/ws/vp-overlay": {"last_seen_ts": 0.0, "message_count": 0},
            "/ws/volume-profile": {"last_seen_ts": 0.0, "message_count": 0},
        }
        self._overlay_updates_seen = 0
        self._emit("session_start", stage="bootstrap", status="started", metrics={"pid": os.getpid()})

    @property
    def session_id(self) -> str:
        return self.ctx.session_id

    @property
    def store(self) -> SessionOpsStore:
        return self._store

    def _append_jsonl(self, row: dict[str, Any]) -> None:
        self._events_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self._events_jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")

    def _emit(
        self,
        event_type: str,
        *,
        stage: str,
        status: str,
        error_code: str | None = None,
        metrics: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = build_event(
            ctx=self.ctx,
            event_type=event_type,
            stage=stage,
            status=status,
            error_code=error_code,
            metrics=metrics,
            artifacts=artifacts,
            payload=payload,
        )
        self._append_jsonl(event)
        self._store.upsert_event(event)
        return event

    def record_preflight(self, metrics: dict[str, Any]) -> dict[str, Any]:
        return self._emit("preflight", stage="preflight", status="ok", metrics=metrics)

    def record_axis_update(self, payload: dict[str, Any], *, status: str = "ok") -> dict[str, Any]:
        return self._emit("axis_update", stage="ocr", status=status, payload=payload)

    def record_overlay_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._overlay_updates_seen += 1
        return self._emit(
            "overlay_update",
            stage="overlay",
            status="ok",
            metrics={"overlay_updates_seen": self._overlay_updates_seen},
            payload=payload,
        )

    def record_ws_health(self, ws_path: str, *, status: str = "ok", details: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        entry = self._ws_health.setdefault(ws_path, {"last_seen_ts": 0.0, "message_count": 0})
        entry["last_seen_ts"] = now
        entry["message_count"] = int(entry.get("message_count", 0)) + 1
        return self._emit(
            "ws_health",
            stage="ws",
            status=status,
            metrics={"ws_path": ws_path, "last_seen_ts": now, "message_count": entry["message_count"]},
            payload=details or {},
        )

    def record_incident(self, *, error_code: str, stage: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        code = error_code if error_code in FAILURE_TAXONOMY else "health_unavailable"
        return self._emit("incident", stage=stage, status="failed", error_code=code, payload=payload or {})

    def close_session(self, status: str = "ended") -> dict[str, Any]:
        return self._emit("session_end", stage="finalize", status=status)

    def _http_json(self, url: str, timeout_s: float = 2.5) -> dict[str, Any] | None:
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "sessionops/1.0"}, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else None
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            return None

    async def run_gate(
        self,
        *,
        distributor_base_url: str,
        ocr_status_fetcher: Any,
        ocr_debug_fetcher: Any,
        continuity_seconds: float = 2.0,
        max_ws_stale_seconds: float = 8.0,
    ) -> dict[str, Any]:
        started = time.time()
        base = distributor_base_url.rstrip("/")
        timeline_path = self._session_dir_root / self.session_id / "gate_timeline.jsonl"
        timeline_path.parent.mkdir(parents=True, exist_ok=True)

        def append_timeline(step: dict[str, Any]) -> None:
            with timeline_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(step, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")

        failures: list[str] = []
        steps: list[dict[str, Any]] = []

        health = await asyncio.to_thread(self._http_json, f"{base}/health")
        step = {"step": "health", "ok": bool(health and health.get("ok")), "ts": time.time()}
        steps.append(step)
        append_timeline(step)
        if not step["ok"]:
            failures.append("health_unavailable")

        ready = await asyncio.to_thread(self._http_json, f"{base}/ready")
        step = {"step": "ready", "ok": bool(ready and "ready" in ready), "ts": time.time()}
        steps.append(step)
        append_timeline(step)
        if not step["ok"]:
            failures.append("ready_unavailable")

        debug_status = await asyncio.to_thread(self._http_json, f"{base}/debug/status")
        step = {"step": "debug_status", "ok": bool(debug_status and debug_status.get("ok")), "ts": time.time()}
        steps.append(step)
        append_timeline(step)
        if not step["ok"]:
            failures.append("debug_status_unavailable")

        ocr_status = await ocr_status_fetcher()
        step = {"step": "ocr_status", "ok": bool(isinstance(ocr_status, dict) and ocr_status.get("ok") is not False), "ts": time.time()}
        steps.append(step)
        append_timeline(step)
        if not step["ok"]:
            failures.append("ocr_status_unavailable")

        ocr_debug = await ocr_debug_fetcher()
        axis_status = ""
        if isinstance(ocr_debug, dict):
            axis_status = str((ocr_debug.get("axis") or {}).get("status") or ocr_debug.get("axis_status") or "")
        step = {"step": "ocr_debug", "ok": bool(isinstance(ocr_debug, dict)), "axis_status": axis_status, "ts": time.time()}
        steps.append(step)
        append_timeline(step)
        if not step["ok"]:
            failures.append("ocr_debug_unavailable")
        elif axis_status and axis_status.upper() in {"NO_AXIS", "CALIBRATING"}:
            failures.append("ocr_no_axis")

        ws_now = time.time()
        stale_paths: list[str] = []
        for path, state in self._ws_health.items():
            last_seen = float(state.get("last_seen_ts") or 0.0)
            msg_count = int(state.get("message_count") or 0)
            age = ws_now - last_seen if last_seen > 0 else 10**9
            ws_ok = msg_count > 0 and age <= max_ws_stale_seconds
            st = {"step": f"ws_health:{path}", "ok": ws_ok, "age_s": round(age, 3), "count": msg_count, "ts": time.time()}
            steps.append(st)
            append_timeline(st)
            if not ws_ok:
                stale_paths.append(path)
        if stale_paths:
            failures.append("overlay_ws_stale")

        overlay_before = self._overlay_updates_seen
        await asyncio.sleep(max(0.2, float(continuity_seconds)))
        overlay_after = self._overlay_updates_seen
        continuity_ok = (overlay_after - overlay_before) >= 1
        st = {
            "step": "overlay_continuity",
            "ok": continuity_ok,
            "before": overlay_before,
            "after": overlay_after,
            "delta": overlay_after - overlay_before,
            "ts": time.time(),
        }
        steps.append(st)
        append_timeline(st)
        if not continuity_ok:
            failures.append("overlay_ws_stale")

        if isinstance(ocr_debug, dict):
            geom = ocr_debug.get("geometry") or {}
            drift_steps = geom.get("drift_steps") if isinstance(geom, dict) else None
            if isinstance(drift_steps, list) and drift_steps:
                max_drift = max(abs(float(s.get("drift_px") or 0.0)) for s in drift_steps if isinstance(s, dict))
                drift_ok = max_drift <= 8.0
                st = {"step": "dpi_drift", "ok": drift_ok, "max_drift_px": max_drift, "ts": time.time()}
                steps.append(st)
                append_timeline(st)
                if not drift_ok:
                    failures.append("dpi_drift_detected")

        ok = len(failures) == 0
        primary_error = failures[0] if failures else ""
        report = {
            "ok": ok,
            "session_id": self.session_id,
            "run_id": self.ctx.run_id,
            "started_at_epoch": started,
            "ended_at_epoch": time.time(),
            "elapsed_ms": int((time.time() - started) * 1000),
            "steps": steps,
            "failures": failures,
            "primary_error": primary_error,
            "artifacts": {
                "gate_timeline": str(timeline_path),
            },
        }

        session_dir = self._session_dir_root / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        report_path = session_dir / "gate_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        event = self._emit(
            "gate_result",
            stage="gate",
            status="ready" if ok else "failed",
            error_code=primary_error or None,
            metrics={"steps": len(steps), "failures": len(failures), "elapsed_ms": report["elapsed_ms"]},
            artifacts={
                "gate_report": str(report_path),
                "gate_timeline": str(timeline_path),
            },
            payload=report,
        )
        if not ok:
            self.record_incident(error_code=primary_error, stage="gate", payload=report)

        manifest_path = session_dir / "session.manifest.json"
        manifest = {
            "session_id": self.session_id,
            "run_id": self.ctx.run_id,
            "contract_version": "v1",
            "gate_ok": ok,
            "latest_gate_event_id": event.get("event_id"),
            "artifacts": {
                "session_manifest": str(manifest_path),
                "gate_report": str(report_path),
                "gate_timeline": str(timeline_path),
                "events_jsonl": str(self._events_jsonl_path),
            },
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        return report

    def agent_snapshot(self, *, include_timeline: int = 40) -> dict[str, Any]:
        sessions = self._store.list_sessions(limit=1)
        current = sessions[0] if sessions else None
        timeline = self._store.timeline(limit=max(1, min(include_timeline, 200)))
        incidents = self._store.list_incidents(limit=20)
        return {
            "ok": True,
            "sessionops_contract_version": "v1",
            "active_session_id": self.session_id,
            "current": current,
            "recent_incidents": incidents,
            "recent_timeline": timeline,
            "ws_health": self._ws_health,
            "overlay_updates_seen": self._overlay_updates_seen,
            "recommended_next_action": self._recommend_next_action(incidents, timeline),
        }

    def _recommend_next_action(self, incidents: list[dict[str, Any]], timeline: list[dict[str, Any]]) -> str:
        latest_gate = None
        for ev in timeline:
            if ev.get("session_id") == self.session_id and ev.get("event_type") == "gate_result":
                latest_gate = ev
                break
        if latest_gate and latest_gate.get("status") == "ready":
            return "collect_closure_evidence_bundle"

        current_incidents = [inc for inc in incidents if inc.get("session_id") == self.session_id]
        if current_incidents:
            code = str(current_incidents[0].get("error_code") or "")
            if code == "ocr_no_axis":
                return "run_recalibrate_then_collect_60s_trace"
            if code == "overlay_ws_stale":
                return "restart_ws_clients_and_verify_overlay_continuity"
            if code == "dpi_drift_detected":
                return "run_monitor_dpi_matrix_check"
            if code == "engine_not_started":
                return "start_engine_then_rerun_gate"
        return "run_strict_gate"
