#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from scripts.cen03_incident_packages import build_incident_evidence_index, validate_cen03_incident_packages
except ImportError:
    from cen03_incident_packages import build_incident_evidence_index, validate_cen03_incident_packages

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"

SCENARIOS = [
    {"id": "CEN-01", "ovr_id": "OVR-STAB-QA-01", "title": "Parado 60s"},
    {"id": "CEN-02", "ovr_id": "OVR-STAB-QA-02", "title": "Zoom/escala"},
    {"id": "CEN-03", "ovr_id": "OVR-STAB-QA-03", "title": "OCR degradado"},
    {"id": "CEN-04", "ovr_id": "OVR-STAB-QA-04", "title": "Multi-monitor DPI"},
    {"id": "CEN-05", "ovr_id": "OVR-STAB-QA-05", "title": "Carga real"},
]
CEN04_REQUIRED_DPI = (100, 125, 150)
CEN04_ALLOWED_TRANSITIONS = ("baseline-open", "move-to-monitor")
CEN04_REQUIRED_STEP_IDS = (
    "open_window_on_baseline_monitor",
    "move_window_to_next_monitor",
    "minimize_window_on_target_monitor",
    "restore_window_on_target_monitor",
    "move_window_back_to_baseline_monitor",
)
CEN02_REQUIRED_TRANSITIONS = ("SUSPECT", "FROZEN", "RECALIBRATING")
CEN02_REQUIRED_COMMON_FIELDS = ("screenshot_ref", "trace_ref", "status_endpoint_ref", "expected_vs_observed")
CEN02_REQUIRED_FIELDS_BY_STATE = {
    "SUSPECT": ("trigger_action", "observed_at_utc"),
    "FROZEN": ("freeze_duration_ms", "observed_at_utc"),
    "RECALIBRATING": ("stable_return_ref", "observed_at_utc"),
}
READINESS_CONTRACT_VERSION = "1.1"
MAX_EXECUTIVE_BLOCKERS = 3


def _coerce_observed_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "sim"}
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validador objetivo de prontidao G8 (CEN-01..CEN-05).")
    parser.add_argument("--qa-manifest", type=Path, default=None)
    parser.add_argument("--stress-manifest", type=Path, default=None)
    parser.add_argument("--field-report", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", default=False)
    return parser.parse_args()


def _latest_manifest(glob_pattern: str) -> Optional[Path]:
    rows = sorted(LOGS_DIR.glob(glob_pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[0].resolve() if rows else None


def _load_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _normalize_field_report_entry(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    issues: List[str] = []
    entry = dict(raw)
    result = str(entry.get("result", "")).strip().lower()
    if "pass" not in entry:
        entry["pass"] = result == "pass"
    pass_value = bool(entry.get("pass") is True)
    evidence_ref = str(entry.get("evidence_ref", "")).strip()
    if not evidence_ref:
        evidence_refs = entry.get("evidence_refs", {})
        if isinstance(evidence_refs, dict):
            for key in ("summary_manifest", "trace_jsonl", "screenshot_or_video", "test_logs"):
                value = str(evidence_refs.get(key, "")).strip()
                if value:
                    evidence_ref = value
                    break
    if not evidence_ref:
        issues.append("missing_evidence_ref")
    if pass_value and not evidence_ref:
        issues.append("pass_without_evidence_ref")
    if result and result not in {"pass", "fail", "blocked"}:
        issues.append(f"invalid_result:{result}")
    entry["pass"] = pass_value and bool(evidence_ref)
    entry["evidence_ref"] = evidence_ref
    entry["result"] = result
    return entry, issues


def _actionable_issue(issue_id: str, action: str) -> str:
    return f"{issue_id}|acao:{action}"


def _ensure_actionable(issue: str, default_action: str) -> str:
    text = str(issue).strip()
    if not text:
        return _actionable_issue("invalid_issue", default_action)
    if "|acao:" in text:
        return text
    return _actionable_issue(text, default_action)


def _validate_cen02_transition_evidence(field_entry: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    transition_evidence = field_entry.get("transition_evidence", [])
    if not isinstance(transition_evidence, list):
        return [
            _actionable_issue(
                "CEN-02:transition_evidence_missing_or_invalid",
                "preencher transition_evidence como lista com SUSPECT/FROZEN/RECALIBRATING",
            )
        ]
    rows_by_transition: Dict[str, Dict[str, Any]] = {}
    for row in transition_evidence:
        if not isinstance(row, dict):
            continue
        transition_state = str(row.get("transition_state", "")).strip().upper()
        if not transition_state:
            issues.append(
                _actionable_issue(
                    "CEN-02:transition_without_state",
                    "preencher transition_state para cada item de transition_evidence",
                )
            )
            continue
        if transition_state not in CEN02_REQUIRED_TRANSITIONS:
            issues.append(
                _actionable_issue(
                    f"CEN-02:{transition_state}:unknown_transition",
                    "usar apenas SUSPECT/FROZEN/RECALIBRATING",
                )
            )
            continue
        if transition_state in rows_by_transition:
            issues.append(
                _actionable_issue(
                    f"CEN-02:{transition_state}:duplicated_transition",
                    "manter apenas um registro por transition_state",
                )
            )
            continue
        rows_by_transition[transition_state] = row

    for transition_state in CEN02_REQUIRED_TRANSITIONS:
        row = rows_by_transition.get(transition_state)
        if row is None:
            issues.append(
                _actionable_issue(
                    f"CEN-02:{transition_state}:missing_transition",
                    f"registrar evento {transition_state} no transition_evidence com evidencias completas",
                )
            )
            continue
        observed = _coerce_observed_true(row.get("observed"))
        if not observed:
            issues.append(
                _actionable_issue(
                    f"CEN-02:{transition_state}:observed_not_true",
                    "marcar observed=true quando a transicao for confirmada em campo",
                )
            )
        for field_name in CEN02_REQUIRED_COMMON_FIELDS:
            if not str(row.get(field_name, "")).strip():
                issues.append(
                    _actionable_issue(
                        f"CEN-02:{transition_state}:missing_{field_name}",
                        f"preencher {field_name} para a transicao {transition_state}",
                    )
                )
        normalized_row = dict(row)
        if transition_state in {"SUSPECT", "FROZEN"} and not str(normalized_row.get("observed_at_utc", "")).strip():
            normalized_row["observed_at_utc"] = str(normalized_row.get("event_timestamp_utc", "")).strip()
        for field_name in CEN02_REQUIRED_FIELDS_BY_STATE[transition_state]:
            if not str(normalized_row.get(field_name, "")).strip():
                issues.append(
                    _actionable_issue(
                        f"CEN-02:{transition_state}:missing_{field_name}",
                        f"preencher campo especifico {field_name} para {transition_state}",
                    )
                )
    return issues


def _validate_cen05_field_entry(field_entry: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    session_type = str(field_entry.get("session_type", "")).strip().lower()
    if session_type not in {"manual-field", "manual-field-assisted"}:
        issues.append(
            _actionable_issue(
                "CEN-05:invalid_or_missing_session_type",
                "preencher session_type=manual-field ou manual-field-assisted no field-report",
            )
        )
    result = str(field_entry.get("result", "")).strip().lower()
    if result not in {"pass", "fail", "blocked"}:
        issues.append(
            _actionable_issue(
                "CEN-05:invalid_result",
                "preencher result com pass|fail|blocked",
            )
        )
    return issues


def _load_field_report(path: Optional[Path]) -> Tuple[Dict[str, Any], Dict[str, List[str]], List[str]]:
    report = _load_json(path)
    scenarios_payload = report.get("scenarios", {})
    scenarios: Dict[str, Any] = {}
    scenario_issues: Dict[str, List[str]] = {}
    global_issues: List[str] = []

    if isinstance(scenarios_payload, dict):
        for scenario_id, payload in scenarios_payload.items():
            sid = str(scenario_id).strip()
            if not sid:
                continue
            if not isinstance(payload, dict):
                scenario_issues[sid] = ["invalid_scenario_payload_type"]
                continue
            normalized, issues = _normalize_field_report_entry(payload)
            normalized["scenario_id"] = sid
            if sid == "CEN-02" and normalized.get("result") == "pass":
                issues = [*issues, *_validate_cen02_transition_evidence(normalized)]
            scenarios[sid] = normalized
            if issues:
                scenario_issues[sid] = issues
        return scenarios, scenario_issues, global_issues

    if isinstance(scenarios_payload, list):
        for idx, row in enumerate(scenarios_payload):
            if not isinstance(row, dict):
                global_issues.append(f"invalid_scenarios_list_entry:{idx}")
                continue
            sid = str(row.get("scenario_id", "")).strip()
            if not sid:
                global_issues.append(f"missing_scenario_id:{idx}")
                continue
            normalized, issues = _normalize_field_report_entry(row)
            normalized["scenario_id"] = sid
            if sid == "CEN-02" and normalized.get("result") == "pass":
                issues = [*issues, *_validate_cen02_transition_evidence(normalized)]
            scenarios[sid] = normalized
            if issues:
                scenario_issues[sid] = issues
        return scenarios, scenario_issues, global_issues

    if scenarios_payload:
        global_issues.append("invalid_scenarios_shape")
    return scenarios, scenario_issues, global_issues


def _validate_cen04_field_entry(field_entry: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    matrix = field_entry.get("monitor_dpi_matrix", [])
    if not isinstance(matrix, list) or not matrix:
        return [_actionable_issue("CEN-04:missing_monitor_dpi_matrix", "preencher monitor_dpi_matrix com 100/125/150")]
    dpi_values: set[int] = set()
    monitor_ids: set[str] = set()
    for idx, row in enumerate(matrix):
        if not isinstance(row, dict):
            issues.append(_actionable_issue(f"CEN-04:invalid_monitor_dpi_matrix_row:{idx}", "usar objeto por linha da matriz"))
            continue
        monitor_id = str(row.get("monitor_id", "")).strip()
        if not monitor_id:
            issues.append(_actionable_issue(f"CEN-04:missing_monitor_dpi_matrix_monitor_id:{idx}", "preencher monitor_id unico"))
        elif monitor_id in monitor_ids:
            issues.append(_actionable_issue(f"CEN-04:duplicated_monitor_dpi_matrix_monitor_id:{monitor_id}", "usar monitor_id unico por linha"))
        else:
            monitor_ids.add(monitor_id)
        try:
            dpi = int(row.get("dpi_percent", 0))
            if dpi in dpi_values:
                issues.append(_actionable_issue(f"CEN-04:duplicated_monitor_dpi_matrix_dpi:{dpi}", "usar cada DPI apenas uma vez"))
            dpi_values.add(dpi)
        except (TypeError, ValueError):
            issues.append(_actionable_issue(f"CEN-04:invalid_monitor_dpi_matrix_dpi:{idx}", "preencher dpi_percent inteiro (100,125,150)"))
            continue
        transition = str(row.get("transition", "")).strip()
        if not transition:
            issues.append(_actionable_issue(f"CEN-04:missing_monitor_dpi_matrix_transition:{idx}", "preencher transition"))
        elif transition not in CEN04_ALLOWED_TRANSITIONS:
            issues.append(_actionable_issue(f"CEN-04:invalid_monitor_dpi_matrix_transition:{transition}", "usar baseline-open ou move-to-monitor"))
        if bool(row.get("bounds_ok")) is not True:
            issues.append(_actionable_issue(f"CEN-04:monitor_dpi_matrix_bounds_not_true:{idx}", "corrigir bounds e registrar true"))
        if bool(row.get("overlay_ok")) is not True:
            issues.append(_actionable_issue(f"CEN-04:monitor_dpi_matrix_overlay_not_true:{idx}", "validar overlay antes de aprovar linha"))
        try:
            drift_px = float(row.get("drift_px"))
            if drift_px > 3.0:
                issues.append(_actionable_issue(f"CEN-04:monitor_dpi_matrix_drift_gt_3px:{idx}", "reduzir drift para <= 3.0 px"))
        except (TypeError, ValueError):
            issues.append(_actionable_issue(f"CEN-04:invalid_monitor_dpi_matrix_drift:{idx}", "preencher drift_px numerico"))
        if not str(row.get("evidence_ref", "")).strip():
            issues.append(_actionable_issue(f"CEN-04:missing_monitor_dpi_matrix_evidence_ref:{idx}", "preencher evidence_ref rastreavel"))
    if sorted(dpi_values) != list(CEN04_REQUIRED_DPI):
        issues.append(_actionable_issue("CEN-04:invalid_dpi_coverage_required_100_125_150", "garantir cobertura exata 100/125/150"))

    drift_steps = field_entry.get("drift_steps", field_entry.get("steps", []))
    if not isinstance(drift_steps, list) or not drift_steps:
        issues.append(_actionable_issue("CEN-04:missing_drift_steps", "preencher drift_steps com os 5 passos obrigatorios"))
        return issues

    observed_step_ids: set[str] = set()
    for idx, row in enumerate(drift_steps):
        if not isinstance(row, dict):
            issues.append(_actionable_issue(f"CEN-04:invalid_drift_step_row:{idx}", "usar objeto por passo"))
            continue
        step_id = str(row.get("step_id", "")).strip()
        if not step_id:
            issues.append(_actionable_issue(f"CEN-04:missing_drift_step_id:{idx}", "preencher step_id"))
            continue
        if step_id in observed_step_ids:
            issues.append(_actionable_issue(f"CEN-04:duplicated_drift_step_id:{step_id}", "remover duplicidade de step_id"))
        observed_step_ids.add(step_id)
        if not str(row.get("monitor_id", "")).strip():
            issues.append(_actionable_issue(f"CEN-04:missing_drift_step_monitor_id:{idx}", "preencher monitor_id do passo"))
        try:
            dpi = int(row.get("dpi_percent"))
            if dpi not in CEN04_REQUIRED_DPI:
                issues.append(_actionable_issue(f"CEN-04:invalid_drift_step_dpi:{idx}", "usar dpi_percent em 100/125/150"))
        except (TypeError, ValueError):
            issues.append(_actionable_issue(f"CEN-04:invalid_drift_step_dpi:{idx}", "preencher dpi_percent inteiro"))
        if not str(row.get("axis_status_before", "")).strip():
            issues.append(_actionable_issue(f"CEN-04:missing_drift_step_axis_status_before:{idx}", "preencher axis_status_before"))
        if not str(row.get("axis_status_after", "")).strip():
            issues.append(_actionable_issue(f"CEN-04:missing_drift_step_axis_status_after:{idx}", "preencher axis_status_after"))
        if not str(row.get("evidence_ref", "")).strip():
            issues.append(_actionable_issue(f"CEN-04:missing_drift_step_evidence_ref:{idx}", "preencher evidence_ref do passo"))
        try:
            drift_px = float(row.get("drift_px"))
            if drift_px > 3.0:
                issues.append(_actionable_issue(f"CEN-04:drift_step_gt_3px:{idx}", "reduzir drift do passo para <= 3.0 px"))
        except (TypeError, ValueError):
            issues.append(_actionable_issue(f"CEN-04:invalid_drift_step_drift:{idx}", "preencher drift_px numerico"))

    for required_step in CEN04_REQUIRED_STEP_IDS:
        if required_step not in observed_step_ids:
            issues.append(_actionable_issue(f"CEN-04:missing_required_drift_step:{required_step}", "executar e registrar passo obrigatorio"))
    return issues


def _diagnose_scenario(
    *,
    scenario_id: str,
    local_pass: bool,
    field_pass: bool,
    local_details: str,
    field_details: str,
) -> Dict[str, str]:
    if local_pass and field_pass:
        return {
            "classification": "CONFIRMED_READY",
            "diagnosis": "evidencia local e de campo convergem para prontidao",
            "next_action": "seguir para monitoramento diario e manter baseline de evidencias",
        }
    if local_pass and not field_pass:
        return {
            "classification": "FALSE_POSITIVE_RISK",
            "diagnosis": f"local indica pronto, mas campo nao confirmou ({field_details})",
            "next_action": f"coletar evidencia objetiva de campo para {scenario_id} e bloquear promocao ate pass=true com evidence_ref",
        }
    if not local_pass and field_pass:
        return {
            "classification": "FALSE_NEGATIVE_RISK",
            "diagnosis": "campo indica pronto, mas validacao local falhou (risco de falso negativo)",
            "next_action": f"auditar gate local ({local_details}) e alinhar regra com evidencia real confirmada de {scenario_id}",
        }
    return {
        "classification": "CONFIRMED_NOT_READY",
        "diagnosis": f"local e campo convergem para falha ({local_details}; {field_details})",
        "next_action": f"tratar causa raiz de {scenario_id}, repetir validacao local e anexar evidence_ref de campo",
    }


def _scenario_result(
    scenario: Dict[str, str],
    qa_manifest: Dict[str, Any],
    stress_manifest: Dict[str, Any],
    field_scenarios: Dict[str, Any],
    field_report_issues: Dict[str, List[str]],
) -> Dict[str, Any]:
    scenario_id = scenario["id"]
    ovr_id = scenario["ovr_id"]
    gaps: List[Dict[str, str]] = []

    local_pass = False
    local_details = "sem evidência local"
    if scenario_id != "CEN-05":
        ovr_status = qa_manifest.get("ovr_status", {})
        entry = ovr_status.get(ovr_id, {}) if isinstance(ovr_status, dict) else {}
        state = entry.get("state", "missing")
        local_pass = state == "partial-done"
        local_details = f"ovr_status.{ovr_id}.state={state}"
        if not local_pass:
            gaps.append(
                {
                    "gap_id": f"GAP-{scenario_id}-LOCAL",
                    "status": "FAIL",
                    "reason": f"evidencia local insuficiente ({local_details})",
                }
            )
    else:
        gate = stress_manifest.get("gate", {})
        gate_ok = bool(gate.get("ok"))
        local_pass = bool(stress_manifest) and gate_ok
        local_details = f"stress_gate_ok={int(gate_ok)}"
        if not local_pass:
            failures = gate.get("failures", []) if isinstance(gate, dict) else []
            details = "; ".join(str(item) for item in failures) if failures else "manifesto ausente ou gate inválido"
            gaps.append(
                {
                    "gap_id": "GAP-CEN-05-LOCAL",
                    "status": "FAIL",
                    "reason": details,
                }
            )

    field_entry = field_scenarios.get(scenario_id, {})
    field_issues = field_report_issues.get(scenario_id, [])
    field_pass = bool(isinstance(field_entry, dict) and field_entry.get("pass") is True)
    cen03_incident_index: Dict[str, Any] = {"index": {}, "errors": [], "checked_incidents": 0}
    if scenario_id == "CEN-03" and field_pass:
        cen03_incident_index = build_incident_evidence_index({"scenarios": {"CEN-03": field_entry}})
        field_issues = [*field_issues, *[str(item) for item in cen03_incident_index.get("errors", [])]]
        cen03_validation = validate_cen03_incident_packages({"scenarios": {"CEN-03": field_entry}})
        if not bool(cen03_validation.get("ok", False)):
            field_pass = False
            field_issues = [*field_issues, *[str(item) for item in cen03_validation.get("errors", [])]]
    if scenario_id == "CEN-04" and field_pass and isinstance(field_entry, dict):
        cen04_issues = _validate_cen04_field_entry(field_entry)
        if cen04_issues:
            field_pass = False
            field_issues = [*field_issues, *cen04_issues]
    if scenario_id == "CEN-05" and field_pass and isinstance(field_entry, dict):
        cen05_issues = _validate_cen05_field_entry(field_entry)
        if cen05_issues:
            field_pass = False
            field_issues = [*field_issues, *cen05_issues]
    if scenario_id == "CEN-03":
        field_issues = [
            _ensure_actionable(
                item,
                "corrigir incident_packages (canais hud/status_endpoint/trace_jsonl, transicoes e evidence_ref) e reenviar report",
            )
            for item in field_issues
        ]
    if scenario_id == "CEN-05":
        field_issues = [
            _ensure_actionable(
                item,
                "completar evidencia de campo CEN-05 com session_type e evidence_ref antes do strict",
            )
            for item in field_issues
        ]
    field_details = "pass=true" if field_pass else "pass!=true"
    if field_issues:
        field_details = ",".join(field_issues)
    if not field_pass:
        reason = "evidencia de campo ausente ou sem pass=true"
        if field_issues:
            reason = f"field-report invalido: {','.join(field_issues)}"
        gaps.append(
            {
                "gap_id": f"GAP-{scenario_id}-FIELD",
                "status": "FAIL",
                "reason": reason,
            }
        )

    scenario_pass = local_pass and field_pass
    diagnosis = _diagnose_scenario(
        scenario_id=scenario_id,
        local_pass=local_pass,
        field_pass=field_pass,
        local_details=local_details,
        field_details=field_details,
    )
    diagnostics = {
        "local_pass": local_pass,
        "field_pass": field_pass,
        "local_details": local_details,
        "field_details": field_details,
        "field_issue_count": len(field_issues),
        "gap_count": len(gaps),
    }
    return {
        "scenario_id": scenario_id,
        "title": scenario["title"],
        "ovr_id": ovr_id,
        "status": "PASS" if scenario_pass else "FAIL",
        "classification": diagnosis["classification"],
        "diagnosis": diagnosis["diagnosis"],
        "next_action": diagnosis["next_action"],
        "local_validation": {"pass": local_pass, "details": local_details},
        "field_validation": {
            "pass": field_pass,
            "evidence_ref": field_entry.get("evidence_ref", "") if isinstance(field_entry, dict) else "",
            "details": field_details,
            "issues": field_issues,
            "incident_evidence_index": cen03_incident_index.get("index", {}) if scenario_id == "CEN-03" else {},
        },
        "gaps": gaps,
        "diagnostics": diagnostics,
    }


def _build_executive_summary(
    *,
    g8_ready: bool,
    scenario_results: List[Dict[str, Any]],
    field_report_global_issues: List[str],
) -> Dict[str, Any]:
    short_status = "PASS" if g8_ready else "FAIL"
    blockers: List[Dict[str, str]] = []
    for row in scenario_results:
        for gap in row.get("gaps", []):
            blockers.append(
                {
                    "scenario_id": str(row.get("scenario_id", "")),
                    "gap_id": str(gap.get("gap_id", "")),
                    "reason": str(gap.get("reason", "")).strip(),
                }
            )
    for issue in field_report_global_issues:
        blockers.append(
            {
                "scenario_id": "GLOBAL",
                "gap_id": "GAP-FIELD-REPORT-GLOBAL",
                "reason": str(issue),
            }
        )
    top_blockers = blockers[:MAX_EXECUTIVE_BLOCKERS]
    if g8_ready:
        recommendation = "Promover monitoramento diario com baseline atual."
    else:
        recommendation = "Bloquear promocao e tratar top blockers antes do proximo gate."
    return {
        "status": short_status,
        "g8_ready": g8_ready,
        "top_blockers": top_blockers,
        "blocker_count": len(blockers),
        "recommendation": recommendation,
    }


def _render_summary(
    path: Path,
    g8_ready: bool,
    scenario_results: List[Dict[str, Any]],
    qa_manifest_path: Optional[Path],
    stress_manifest_path: Optional[Path],
    field_report_path: Optional[Path],
    field_report_global_issues: List[str],
    executive_summary: Dict[str, Any],
) -> None:
    top_blockers = executive_summary.get("top_blockers", [])
    blocker_text = "; ".join(
        f"{item.get('scenario_id')}:{item.get('gap_id')}:{item.get('reason')}" for item in top_blockers
    )
    lines = [
        "# OVR STAB - G8 readiness validator",
        "",
        "## Executive short output",
        "",
        f"- status: `{executive_summary.get('status', 'FAIL')}`",
        f"- g8_ready: `{int(bool(executive_summary.get('g8_ready', False)))}`",
        f"- top_blockers: `{blocker_text if blocker_text else 'none'}`",
        f"- recommendation: `{executive_summary.get('recommendation', '')}`",
        "",
        f"- g8_ready: `{int(g8_ready)}`",
        f"- qa_manifest: `{qa_manifest_path or 'not-found'}`",
        f"- stress_manifest: `{stress_manifest_path or 'not-found'}`",
        f"- field_report: `{field_report_path or 'not-found'}`",
        f"- field_report_issues: `{'; '.join(field_report_global_issues) if field_report_global_issues else 'none'}`",
        "",
        "| scenario | status | classification | local_validation | field_validation | gaps |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in scenario_results:
        gap_ids = ",".join(item["gap_id"] for item in row["gaps"]) if row["gaps"] else "none"
        lines.append(
            f"| {row['scenario_id']} | {row['status']} | "
            f"{row['classification']} | "
            f"{int(bool(row['local_validation']['pass']))} ({row['local_validation']['details']}) | "
            f"{int(bool(row['field_validation']['pass']))} ({row['field_validation'].get('details', '')}) | {gap_ids} |"
        )
    lines.append("")
    lines.append("## Diagnosis and next action")
    lines.append("")
    for row in scenario_results:
        lines.append(f"- {row['scenario_id']} | {row['classification']} | {row['diagnosis']}")
        lines.append(f"  - next_action: {row['next_action']}")
    lines.append("")
    lines.append("## Gap details")
    lines.append("")
    for row in scenario_results:
        for gap in row["gaps"]:
            lines.append(f"- {row['scenario_id']} | {gap['gap_id']} | {gap['status']} | {gap['reason']}")
    if not any(row["gaps"] for row in scenario_results):
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"ovr-stab-g8-readiness-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    qa_manifest_path = args.qa_manifest or _latest_manifest("ovr-stab-qa-evidence-*/summary.manifest.json")
    stress_manifest_path = args.stress_manifest or _latest_manifest("overlay-ws-stress-regression-*/summary.manifest.json")
    field_report_path = args.field_report if args.field_report else None

    qa_manifest = _load_json(qa_manifest_path)
    stress_manifest = _load_json(stress_manifest_path)
    field_scenarios, field_report_issues, field_report_global_issues = _load_field_report(field_report_path)

    scenario_results = [
        _scenario_result(
            scenario,
            qa_manifest=qa_manifest,
            stress_manifest=stress_manifest,
            field_scenarios=field_scenarios,
            field_report_issues=field_report_issues,
        )
        for scenario in SCENARIOS
    ]
    g8_ready = all(row["status"] == "PASS" for row in scenario_results)
    classification_counts: Dict[str, int] = {}
    for row in scenario_results:
        key = str(row.get("classification", "UNKNOWN"))
        classification_counts[key] = classification_counts.get(key, 0) + 1

    summary_md = out_dir / "summary.md"
    summary_manifest = out_dir / "summary.manifest.json"
    executive_summary = _build_executive_summary(
        g8_ready=g8_ready,
        scenario_results=scenario_results,
        field_report_global_issues=field_report_global_issues,
    )
    _render_summary(
        summary_md,
        g8_ready=g8_ready,
        scenario_results=scenario_results,
        qa_manifest_path=qa_manifest_path,
        stress_manifest_path=stress_manifest_path,
        field_report_path=field_report_path,
        field_report_global_issues=field_report_global_issues,
        executive_summary=executive_summary,
    )
    payload = {
        "runner": "verify_ovr_stab_g8_readiness.py",
        "contract_version": READINESS_CONTRACT_VERSION,
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "g8_ready": g8_ready,
        "classification_counts": classification_counts,
        "executive_summary": executive_summary,
        "scenario_results": scenario_results,
        "artifacts": {"summary_md": str(summary_md), "summary_manifest": str(summary_manifest)},
        "inputs": {
            "qa_manifest": str(qa_manifest_path) if qa_manifest_path else "",
            "stress_manifest": str(stress_manifest_path) if stress_manifest_path else "",
            "field_report": str(field_report_path) if field_report_path else "",
        },
        "field_report_validation": {
            "global_issues": field_report_global_issues,
            "scenario_issues": field_report_issues,
        },
        "report_contract": {
            "scenario_results_required_fields": [
                "scenario_id",
                "status",
                "classification",
                "diagnosis",
                "next_action",
                "local_validation",
                "field_validation",
                "gaps",
                "diagnostics",
            ]
        },
    }
    summary_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    short_blockers = executive_summary.get("top_blockers", [])
    short_blockers_text = "; ".join(
        f"{item.get('scenario_id')}:{item.get('gap_id')}" for item in short_blockers
    ) or "none"
    print(
        "G8_EXECUTIVE "
        f"status={executive_summary.get('status', 'FAIL')} "
        f"g8_ready={int(bool(executive_summary.get('g8_ready', False)))} "
        f"top_blockers={short_blockers_text}"
    )
    if args.strict and not g8_ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
