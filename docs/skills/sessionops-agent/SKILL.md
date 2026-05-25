# SessionOps Agent Skill

## Purpose
Run deterministic SessionOps for OCR overlay debugging with strict gates and AI-readable artifacts.

## Session Start
1. Call `POST /api/sessionops/run-gate`.
2. If `ok=false`, inspect `primary_error` and `steps`.
3. Use only allowed actions below, then rerun gate.

## Mandatory Gates
- distributor: `/health`, `/ready`, `/debug/status`
- OCR: `/api/ocr-overlay/status`, `/api/ocr-overlay/debug`
- WS liveness: `/ws/vp-overlay`, `/ws/volume-profile`
- overlay continuity: at least one `overlay_update` in continuity window

## Incident Classes
- `engine_not_started`
- `ocr_no_axis`
- `overlay_ws_stale`
- `dpi_drift_detected`
- `health_unavailable`
- `ready_unavailable`
- `debug_status_unavailable`
- `ocr_status_unavailable`
- `ocr_debug_unavailable`

## Allowed Actions
- `POST /api/ocr-overlay/freeze`
- `POST /api/ocr-overlay/unfreeze`
- `POST /api/ocr-overlay/recalibrate`
- `POST /api/ocr-overlay/manual-calibration`
- `POST /api/ocr-overlay/manual-unlock`
- `POST /api/set-active-asset`

## Artifacts
- `distributor/logs/sessionops/<session_id>/session.manifest.json`
- `distributor/logs/sessionops/<session_id>/gate_report.json`
- `distributor/logs/sessionops/<session_id>/gate_timeline.jsonl`
- `distributor/logs/sessionops/events.jsonl`

## Closure
Session closes only when latest gate is `ok=true` and `recommended_next_action=collect_closure_evidence_bundle`.
