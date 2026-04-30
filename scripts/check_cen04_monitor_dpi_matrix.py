#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"

CEN04_REQUIRED_DPI = (100, 125, 150)
CEN04_ALLOWED_TRANSITIONS = ("baseline-open", "move-to-monitor")
CEN04_REQUIRED_STEP_IDS = (
    "open_window_on_baseline_monitor",
    "move_window_to_next_monitor",
    "minimize_window_on_target_monitor",
    "restore_window_on_target_monitor",
    "move_window_back_to_baseline_monitor",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditoria isolada de monitor_dpi_matrix/drift_steps (CEN-04).")
    parser.add_argument("--field-report", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", default=False)
    return parser.parse_args()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _issue(issue_id: str, action: str) -> str:
    return f"{issue_id}|acao:{action}"


def validate_cen04_field_matrix(field_report_payload: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = field_report_payload.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return {
            "ok": False,
            "checked_rows": 0,
            "checked_steps": 0,
            "issues": [_issue("CEN-04:scenarios_missing_or_invalid", "corrigir shape de field_report.scenarios para objeto")],
        }

    cen04 = scenarios.get("CEN-04", {})
    if not isinstance(cen04, dict):
        return {
            "ok": False,
            "checked_rows": 0,
            "checked_steps": 0,
            "issues": [_issue("CEN-04:scenario_missing_or_invalid", "preencher scenarios.CEN-04 com payload valido")],
        }

    matrix = cen04.get("monitor_dpi_matrix", [])
    if not isinstance(matrix, list) or not matrix:
        return {
            "ok": False,
            "checked_rows": 0,
            "checked_steps": 0,
            "issues": [_issue("CEN-04:monitor_dpi_matrix_missing_or_empty", "preencher matriz com 100/125/150")],
        }

    issues: List[str] = []
    observed_dpi: set[int] = set()
    seen_dpi: set[int] = set()
    seen_monitor_ids: set[str] = set()
    for idx, row in enumerate(matrix):
        if not isinstance(row, dict):
            issues.append(_issue(f"CEN-04:matrix_row_invalid:{idx}", "corrigir linha para objeto"))
            continue
        monitor_id = str(row.get("monitor_id", "")).strip()
        if not monitor_id:
            issues.append(_issue(f"CEN-04:matrix_missing_monitor_id:{idx}", "preencher monitor_id"))
        elif monitor_id in seen_monitor_ids:
            issues.append(_issue(f"CEN-04:matrix_duplicated_monitor_id:{monitor_id}", "usar monitor_id unico por linha"))
        else:
            seen_monitor_ids.add(monitor_id)

        try:
            dpi = int(row.get("dpi_percent", 0))
            observed_dpi.add(dpi)
            if dpi in seen_dpi:
                issues.append(_issue(f"CEN-04:matrix_duplicated_dpi:{dpi}", "manter apenas um monitor por DPI"))
            seen_dpi.add(dpi)
            if dpi not in CEN04_REQUIRED_DPI:
                issues.append(_issue(f"CEN-04:matrix_invalid_dpi:{dpi}", "usar apenas 100, 125 e 150"))
        except (TypeError, ValueError):
            issues.append(_issue(f"CEN-04:matrix_dpi_not_integer:{idx}", "ajustar dpi_percent para inteiro"))

        transition = str(row.get("transition", "")).strip()
        if transition not in CEN04_ALLOWED_TRANSITIONS:
            issues.append(
                _issue(
                    f"CEN-04:matrix_invalid_transition:{idx}",
                    "usar transition baseline-open para monitor base e move-to-monitor para demais",
                )
            )
        if bool(row.get("bounds_ok")) is not True:
            issues.append(_issue(f"CEN-04:matrix_bounds_not_true:{idx}", "confirmar bounds_ok=true em campo"))
        if bool(row.get("overlay_ok")) is not True:
            issues.append(_issue(f"CEN-04:matrix_overlay_not_true:{idx}", "confirmar overlay_ok=true em campo"))
        if not str(row.get("evidence_ref", "")).strip():
            issues.append(_issue(f"CEN-04:matrix_missing_evidence_ref:{idx}", "anexar evidence_ref rastreavel"))
        try:
            drift = float(row.get("drift_px"))
            if drift > 3.0:
                issues.append(_issue(f"CEN-04:matrix_drift_gt_3px:{idx}", "reduzir drift para <= 3.0 px"))
        except (TypeError, ValueError):
            issues.append(_issue(f"CEN-04:matrix_drift_invalid:{idx}", "preencher drift_px numerico"))

    if sorted(observed_dpi) != list(CEN04_REQUIRED_DPI):
        issues.append(_issue("CEN-04:matrix_dpi_coverage_invalid", "garantir cobertura exata 100/125/150 sem duplicidade"))

    steps = cen04.get("drift_steps", cen04.get("steps", []))
    if not isinstance(steps, list) or not steps:
        issues.append(_issue("CEN-04:drift_steps_missing_or_empty", "preencher drift_steps com os 5 passos obrigatorios"))
        steps = []

    observed_step_ids: set[str] = set()
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            issues.append(_issue(f"CEN-04:step_invalid:{idx}", "corrigir passo para objeto"))
            continue
        step_id = str(step.get("step_id", "")).strip()
        if not step_id:
            issues.append(_issue(f"CEN-04:step_missing_step_id:{idx}", "preencher step_id"))
        elif step_id in observed_step_ids:
            issues.append(_issue(f"CEN-04:step_duplicated_step_id:{step_id}", "remover duplicidade de step_id"))
        else:
            observed_step_ids.add(step_id)
        if not str(step.get("monitor_id", "")).strip():
            issues.append(_issue(f"CEN-04:step_missing_monitor_id:{idx}", "preencher monitor_id do passo"))
        try:
            step_dpi = int(step.get("dpi_percent"))
            if step_dpi not in CEN04_REQUIRED_DPI:
                issues.append(_issue(f"CEN-04:step_invalid_dpi:{idx}", "usar dpi_percent 100/125/150"))
        except (TypeError, ValueError):
            issues.append(_issue(f"CEN-04:step_dpi_not_integer:{idx}", "preencher dpi_percent inteiro"))
        if not str(step.get("axis_status_before", "")).strip():
            issues.append(_issue(f"CEN-04:step_missing_axis_status_before:{idx}", "preencher axis_status_before"))
        if not str(step.get("axis_status_after", "")).strip():
            issues.append(_issue(f"CEN-04:step_missing_axis_status_after:{idx}", "preencher axis_status_after"))
        if not str(step.get("evidence_ref", "")).strip():
            issues.append(_issue(f"CEN-04:step_missing_evidence_ref:{idx}", "anexar evidence_ref do passo"))
        try:
            step_drift = float(step.get("drift_px"))
            if step_drift > 3.0:
                issues.append(_issue(f"CEN-04:step_drift_gt_3px:{idx}", "reduzir drift_px do passo para <= 3.0"))
        except (TypeError, ValueError):
            issues.append(_issue(f"CEN-04:step_drift_invalid:{idx}", "preencher drift_px numerico do passo"))

    for required_step_id in CEN04_REQUIRED_STEP_IDS:
        if required_step_id not in observed_step_ids:
            issues.append(_issue(f"CEN-04:step_missing_required:{required_step_id}", "executar e registrar passo obrigatorio"))

    return {"ok": len(issues) == 0, "checked_rows": len(matrix), "checked_steps": len(steps), "issues": issues}


def _build_summary_md(path: Path, result: Dict[str, Any], field_report: Path) -> None:
    lines: List[str] = [
        "# CEN-04 monitor_dpi_matrix audit",
        "",
        f"- ok: `{int(bool(result.get('ok')) )}`",
        f"- field_report: `{field_report}`",
        f"- checked_rows: `{int(result.get('checked_rows', 0))}`",
        f"- checked_steps: `{int(result.get('checked_steps', 0))}`",
        "",
        "## Acao do operador",
        "",
    ]
    issues = result.get("issues", [])
    if isinstance(issues, list) and issues:
        for item in issues:
            lines.append(f"- {item}")
    else:
        lines.append("- sem pendencias para CEN-04")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"cen04-monitor-dpi-matrix-audit-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = _load_json(args.field_report.resolve())
    result = validate_cen04_field_matrix(payload)
    output_payload: Dict[str, Any] = {
        "runner": "check_cen04_monitor_dpi_matrix.py",
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "field_report": str(args.field_report.resolve()),
        **result,
    }
    summary_md = out_dir / "summary.md"
    summary_manifest = out_dir / "summary.manifest.json"
    _build_summary_md(summary_md, result, args.field_report.resolve())
    summary_manifest.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    if args.strict and not bool(result.get("ok")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
