#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from scripts.cen03_incident_packages import build_incident_evidence_index, validate_cen03_incident_packages
except ImportError:
    from cen03_incident_packages import build_incident_evidence_index, validate_cen03_incident_packages

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"

EXPECTED_BUNDLE_FILES = (
    "summary.md",
    "summary.manifest.json",
    "field_execution.checklist.md",
    "cen04_drift_worksheet.md",
    "cen02.operator.template.md",
    "cen02.minimum_checks.json",
    "cen02.field_report.fixture.json",
    "cen02.field_report.fixture.integrity.json",
    "commands.ready.md",
    "preopen.md",
)
EXPECTED_QA_FILES = (
    "summary.csv",
    "summary.md",
    "summary.manifest.json",
    "target_protocols.manifest.json",
    "target_protocols.checklist.md",
)
EXPECTED_STRESS_FILES = (
    "stress.csv",
    "summary.md",
    "summary.manifest.json",
)
CEN02_REQUIRED_TRANSITIONS = ("SUSPECT", "FROZEN", "RECALIBRATING")
CEN02_REQUIRED_EVIDENCE_FIELDS = ("screenshot_ref", "trace_ref", "status_endpoint_ref", "expected_vs_observed")
CEN02_REQUIRED_FIELDS_BY_STATE = {
    "SUSPECT": ("trigger_action", "observed_at_utc"),
    "FROZEN": ("freeze_duration_ms", "observed_at_utc"),
    "RECALIBRATING": ("stable_return_ref", "observed_at_utc"),
}
CEN04_REQUIRED_DPI = (100, 125, 150)
CEN04_ALLOWED_TRANSITIONS = ("baseline-open", "move-to-monitor")
CEN04_REQUIRED_STEP_IDS = (
    "open_window_on_baseline_monitor",
    "move_window_to_next_monitor",
    "minimize_window_on_target_monitor",
    "restore_window_on_target_monitor",
    "move_window_back_to_baseline_monitor",
)
FIELD_BUNDLE_CONTRACT_VERSION = "1.1"


def _coerce_observed_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "sim"}
    return False


def _actionable_issue(issue_id: str, action: str) -> str:
    return f"{issue_id}|acao:{action}"


def _ensure_actionable(issue: str, default_action: str) -> str:
    text = str(issue).strip()
    if not text:
        return _actionable_issue("invalid_issue", default_action)
    if "|acao:" in text:
        return text
    return _actionable_issue(text, default_action)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bundle final de execucao de campo para CEN-02..CEN-05.")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--field-report", type=Path, default=None)
    parser.add_argument("--skip-local-qa", action="store_true", default=False)
    parser.add_argument("--skip-stress", action="store_true", default=False)
    parser.add_argument("--duration-scale", type=float, default=1.0)
    parser.add_argument("--frame-scale", type=float, default=1.0)
    parser.add_argument("--strict", action="store_true", default=False)
    return parser.parse_args()


def _run(cmd: List[str], out_dir: Path, step_id: str) -> Dict[str, Any]:
    stdout_log = out_dir / f"{step_id}.stdout.log"
    stderr_log = out_dir / f"{step_id}.stderr.log"
    started = time.time()
    with stdout_log.open("w", encoding="utf-8") as out_f, stderr_log.open("w", encoding="utf-8") as err_f:
        proc = subprocess.run(cmd, cwd=str(ROOT), check=False, shell=False, stdout=out_f, stderr=err_f)
    return {
        "id": step_id,
        "command": cmd,
        "exit_code": int(proc.returncode),
        "ok": int(proc.returncode) == 0,
        "elapsed_s": round(time.time() - started, 3),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }


def _validate_required_files(base_dir: Path, expected_files: Tuple[str, ...]) -> Dict[str, Any]:
    missing: List[str] = []
    for rel in expected_files:
        target = base_dir / rel
        if not target.exists() or target.stat().st_size <= 0:
            missing.append(str(target))
    return {"ok": len(missing) == 0, "missing": missing, "checked_count": len(expected_files)}


def _validate_runner_logs(base_dir: Path, step_ids: Tuple[str, ...]) -> Dict[str, Any]:
    missing: List[str] = []
    for step_id in step_ids:
        for suffix in ("stdout.log", "stderr.log"):
            target = base_dir / f"{step_id}.{suffix}"
            if not target.exists():
                missing.append(str(target))
    return {"ok": len(missing) == 0, "missing": missing, "checked_count": len(step_ids) * 2}


def _latest_dir(prefix: str) -> Path | None:
    rows = sorted(
        (item for item in LOGS_DIR.glob(f"{prefix}-*") if item.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not rows:
        return None
    return rows[0].resolve()


def _resolve_cen04_audit_manifest(steps: List[Dict[str, Any]], out_dir: Path) -> Path | None:
    for step in steps:
        if str(step.get("id", "")) == "step_04_cen04_matrix_audit":
            if bool(step.get("ok")):
                return out_dir / "cen04-matrix-audit" / "summary.manifest.json"
            return None
    return None


def _step_ok(steps: List[Dict[str, Any]], step_id: str) -> bool:
    for step in steps:
        if str(step.get("id", "")) == step_id:
            return bool(step.get("ok", False))
    return False


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _validate_cen02_transition_evidence(field_report_payload: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = field_report_payload.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return {"ok": False, "checked_transitions": 0, "errors": ["field_report.scenarios_missing_or_invalid"]}

    cen02 = scenarios.get("CEN-02", {})
    if not isinstance(cen02, dict):
        return {"ok": False, "checked_transitions": 0, "errors": ["field_report.scenarios.CEN-02_missing_or_invalid"]}

    transition_evidence = cen02.get("transition_evidence", [])
    if not isinstance(transition_evidence, list):
        return {
            "ok": False,
            "checked_transitions": 0,
            "errors": [
                "CEN-02.transition_evidence_missing_or_invalid|acao:preencher transition_evidence como lista com SUSPECT/FROZEN/RECALIBRATING"
            ],
        }

    rows_by_transition: Dict[str, Dict[str, Any]] = {}
    for row in transition_evidence:
        if not isinstance(row, dict):
            continue
        transition_state = str(row.get("transition_state", "")).strip().upper()
        if not transition_state:
            errors = [
                "CEN-02:transition_without_state|acao:preencher transition_state para cada item de transition_evidence"
            ]
            return {"ok": False, "checked_transitions": 0, "errors": errors}
        if transition_state not in CEN02_REQUIRED_TRANSITIONS:
            errors = [
                f"CEN-02:{transition_state}:unknown_transition|acao:usar apenas SUSPECT/FROZEN/RECALIBRATING"
            ]
            return {"ok": False, "checked_transitions": 0, "errors": errors}
        if transition_state in rows_by_transition:
            errors = [
                f"CEN-02:{transition_state}:duplicated_transition|acao:manter apenas um registro por transition_state"
            ]
            return {"ok": False, "checked_transitions": 0, "errors": errors}
        rows_by_transition[transition_state] = row

    errors: List[str] = []
    checked_transitions = 0
    for transition_state in CEN02_REQUIRED_TRANSITIONS:
        row = rows_by_transition.get(transition_state)
        if row is None:
            errors.append(
                f"CEN-02:{transition_state}:missing_transition|acao:registrar evento {transition_state} com evidencias minimas"
            )
            continue
        checked_transitions += 1
        if not _coerce_observed_true(row.get("observed")):
            errors.append(
                f"CEN-02:{transition_state}:observed_not_true|acao:marcar observed=true apos confirmacao em campo"
            )
        for field_name in CEN02_REQUIRED_EVIDENCE_FIELDS:
            value = str(row.get(field_name, "")).strip()
            if not value:
                errors.append(
                    f"CEN-02:{transition_state}:missing_{field_name}|acao:preencher {field_name} para a transicao {transition_state}"
                )
        normalized_row = dict(row)
        if transition_state in {"SUSPECT", "FROZEN"} and not str(normalized_row.get("observed_at_utc", "")).strip():
            normalized_row["observed_at_utc"] = str(normalized_row.get("event_timestamp_utc", "")).strip()
        for field_name in CEN02_REQUIRED_FIELDS_BY_STATE[transition_state]:
            value = str(normalized_row.get(field_name, "")).strip()
            if not value:
                errors.append(
                    f"CEN-02:{transition_state}:missing_{field_name}|acao:preencher campo especifico {field_name} para {transition_state}"
                )

    return {"ok": len(errors) == 0, "checked_transitions": checked_transitions, "errors": errors}


def _validate_cen04_field_matrix(field_report_payload: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = field_report_payload.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return {"ok": False, "checked_rows": 0, "checked_steps": 0, "errors": ["field_report.scenarios_missing_or_invalid"]}

    cen04 = scenarios.get("CEN-04", {})
    if not isinstance(cen04, dict):
        return {"ok": False, "checked_rows": 0, "checked_steps": 0, "errors": ["field_report.scenarios.CEN-04_missing_or_invalid"]}

    matrix = cen04.get("monitor_dpi_matrix", [])
    if not isinstance(matrix, list) or not matrix:
        return {"ok": False, "checked_rows": 0, "checked_steps": 0, "errors": ["CEN-04.monitor_dpi_matrix_missing_or_empty"]}

    errors: List[str] = []
    seen_monitors: set[str] = set()
    seen_dpi: set[int] = set()
    observed_dpi: set[int] = set()
    for idx, row in enumerate(matrix):
        if not isinstance(row, dict):
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:invalid_row_type")
            continue
        monitor_id = str(row.get("monitor_id", "")).strip()
        if not monitor_id:
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:missing_monitor_id")
        elif monitor_id in seen_monitors:
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:duplicated_monitor_id:{monitor_id}")
        else:
            seen_monitors.add(monitor_id)

        try:
            dpi = int(row.get("dpi_percent", 0))
            observed_dpi.add(dpi)
            if dpi in seen_dpi:
                errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:duplicated_dpi_percent:{dpi}")
            seen_dpi.add(dpi)
            if dpi not in CEN04_REQUIRED_DPI:
                errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:invalid_dpi_percent:{dpi}")
        except (TypeError, ValueError):
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:dpi_percent_not_integer")

        transition = str(row.get("transition", "")).strip()
        if not transition:
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:missing_transition")
        elif transition not in CEN04_ALLOWED_TRANSITIONS:
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:invalid_transition:{transition}")

        if bool(row.get("bounds_ok")) is not True:
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:bounds_ok_not_true")
        if bool(row.get("overlay_ok")) is not True:
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:overlay_ok_not_true")

        try:
            drift = float(row.get("drift_px"))
            if drift > 3.0:
                errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:drift_px_gt_3:{drift}")
        except (TypeError, ValueError):
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:drift_px_invalid")

        if not str(row.get("evidence_ref", "")).strip():
            errors.append(f"CEN-04.monitor_dpi_matrix[{idx}]:missing_evidence_ref")

    if sorted(observed_dpi) != list(CEN04_REQUIRED_DPI):
        errors.append("CEN-04.monitor_dpi_matrix_invalid_dpi_coverage_required_100_125_150")

    steps = cen04.get("drift_steps", cen04.get("steps", []))
    if not isinstance(steps, list) or not steps:
        errors.append("CEN-04.drift_steps_missing_or_empty")
        steps = []

    observed_step_ids: set[str] = set()
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"CEN-04.drift_steps[{idx}]:invalid_row_type")
            continue
        step_id = str(step.get("step_id", "")).strip()
        if not step_id:
            errors.append(f"CEN-04.drift_steps[{idx}]:missing_step_id")
            continue
        if step_id in observed_step_ids:
            errors.append(f"CEN-04.drift_steps[{idx}]:duplicated_step_id:{step_id}")
        observed_step_ids.add(step_id)
        monitor_id = str(step.get("monitor_id", "")).strip()
        if not monitor_id:
            errors.append(f"CEN-04.drift_steps[{idx}]:missing_monitor_id")
        try:
            step_dpi = int(step.get("dpi_percent"))
            if step_dpi not in CEN04_REQUIRED_DPI:
                errors.append(f"CEN-04.drift_steps[{idx}]:invalid_dpi_percent:{step_dpi}")
        except (TypeError, ValueError):
            errors.append(f"CEN-04.drift_steps[{idx}]:dpi_percent_not_integer")
        if not str(step.get("axis_status_before", "")).strip():
            errors.append(f"CEN-04.drift_steps[{idx}]:missing_axis_status_before")
        if not str(step.get("axis_status_after", "")).strip():
            errors.append(f"CEN-04.drift_steps[{idx}]:missing_axis_status_after")
        if not str(step.get("evidence_ref", "")).strip():
            errors.append(f"CEN-04.drift_steps[{idx}]:missing_evidence_ref")
        try:
            drift = float(step.get("drift_px"))
            if drift > 3.0:
                errors.append(f"CEN-04.drift_steps[{idx}]:drift_px_gt_3:{drift}")
        except (TypeError, ValueError):
            errors.append(f"CEN-04.drift_steps[{idx}]:drift_px_invalid")

    for step_id in CEN04_REQUIRED_STEP_IDS:
        if step_id not in observed_step_ids:
            errors.append(f"CEN-04.drift_steps:missing_required_step:{step_id}")

    return {"ok": len(errors) == 0, "checked_rows": len(matrix), "checked_steps": len(steps), "errors": errors}


def _validate_cen05_field_report(field_report_payload: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = field_report_payload.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return {"ok": False, "errors": ["field_report.scenarios_missing_or_invalid"], "checked": 0}
    cen05 = scenarios.get("CEN-05", {})
    if not isinstance(cen05, dict):
        return {
            "ok": False,
            "errors": [
                _actionable_issue(
                    "CEN-05:missing_or_invalid_payload",
                    "preencher bloco CEN-05 no field-report com result, session_type e evidence_ref",
                )
            ],
            "checked": 0,
        }
    errors: List[str] = []
    if str(cen05.get("result", "")).strip().lower() not in {"pass", "fail", "blocked"}:
        errors.append(_actionable_issue("CEN-05:invalid_result", "usar result=pass|fail|blocked"))
    if str(cen05.get("session_type", "")).strip().lower() not in {"manual-field", "manual-field-assisted"}:
        errors.append(
            _actionable_issue(
                "CEN-05:invalid_or_missing_session_type",
                "preencher session_type=manual-field ou manual-field-assisted",
            )
        )
    if not str(cen05.get("evidence_ref", "")).strip():
        errors.append(
            _actionable_issue("CEN-05:missing_evidence_ref", "anexar evidence_ref rastreavel da sessao real CEN-05")
        )
    return {"ok": len(errors) == 0, "errors": errors, "checked": 1}


def _validate_bundle_contract(out_dir: Path) -> Dict[str, Any]:
    checks = {
        "commands": out_dir / "commands.ready.md",
        "checklist": out_dir / "field_execution.checklist.md",
        "worksheet": out_dir / "cen04_drift_worksheet.md",
        "preopen": out_dir / "preopen.md",
    }
    errors: List[str] = []
    for key, file_path in checks.items():
        if not file_path.exists():
            errors.append(f"{key}_missing:{file_path}")
            continue
        content = file_path.read_text(encoding="utf-8")
        if key == "commands":
            for token in (
                "cen04_drift_worksheet.md",
                "check_cen04_monitor_dpi_matrix.py",
                "cen02.operator.template.md",
                "cen02.minimum_checks.json",
                "verify_cen05_preflight.py",
            ):
                if token not in content:
                    errors.append(f"commands_missing_token:{token}")
        elif key == "checklist":
            for token in ("## CEN-04 Multi-monitor 100/125/150", "#### Criterios de aceite instantaneos (CEN-04)"):
                if token not in content:
                    errors.append(f"checklist_missing_token:{token}")
        elif key == "worksheet":
            for token in ("## Gate CEN-04", "drift_px <= 3.0"):
                if token not in content:
                    errors.append(f"worksheet_missing_token:{token}")
        elif key == "preopen":
            if "CEN-05 preflight validator" not in content and "CEN-05 preopen" not in content:
                errors.append("preopen_missing_token:CEN-05 preflight validator")
    return {"ok": len(errors) == 0, "checked_files": len(checks), "errors": errors}


def _validate_preopen_contract(preopen_payload: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(preopen_payload, dict) or not preopen_payload:
        return {"ok": False, "errors": ["preopen_manifest_missing_or_invalid"]}
    if str(preopen_payload.get("preopen_status_code", "")).strip() not in {"PREOPEN_GO", "PREOPEN_BLOCKED"}:
        errors.append("preopen_missing_or_invalid_status_code")
    checks = preopen_payload.get("checks", [])
    if not isinstance(checks, list) or not checks:
        errors.append("preopen_missing_checks")
    else:
        for idx, row in enumerate(checks):
            if not isinstance(row, dict):
                errors.append(f"preopen_invalid_check_row:{idx}")
                continue
            for key in ("check_id", "status", "preopen_status_code", "details", "next_step"):
                if key not in row:
                    errors.append(f"preopen_check_missing_field:{idx}:{key}")
    next_actions = preopen_payload.get("next_actions", [])
    if not isinstance(next_actions, list) or not next_actions:
        errors.append("preopen_missing_next_actions")
    else:
        for idx, row in enumerate(next_actions):
            if not isinstance(row, dict):
                errors.append(f"preopen_invalid_next_action_row:{idx}")
                continue
            for key in ("priority", "check_id", "status_code", "action", "command", "exit_criteria"):
                if key not in row:
                    errors.append(f"preopen_next_action_missing_field:{idx}:{key}")
    operational_messages = preopen_payload.get("operational_messages", [])
    if not isinstance(operational_messages, list) or not operational_messages:
        errors.append("preopen_missing_operational_messages")
    return {"ok": len(errors) == 0, "errors": errors}


def _build_commands_md(path: Path, refs: Dict[str, str]) -> None:
    lines: List[str] = [
        "# CEN-02..CEN-05 command bundle",
        "",
        "## 1) Gerar evidencias locais + checklist de campo",
        "",
        "python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-02 --require-ovr OVR-STAB-QA-03 --require-ovr OVR-STAB-QA-04 --require-ovr OVR-STAB-QA-05 --require-ovr OVR-STAB-OBS-09 --cen05-stress-manifest \"<stress-summary-manifest>\"",
        "",
        "## 2) Executar stress de carga CEN-05",
        "",
        "python scripts/run_overlay_ws_stress_regression.py --duration-scale 1.0 --frame-scale 1.0",
        "",
        "## 3) Rodar pacote estrito orientado ao operador para CEN-03",
        "",
        "python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-03 --require-ovr OVR-STAB-OBS-09 --cen05-stress-manifest \"<stress-summary-manifest>\"",
        "",
        "## 4) Validar prontidao consolidada G8 (CEN-01..05)",
        "",
        "python scripts/verify_ovr_stab_g8_readiness.py --strict --qa-manifest \"<qa-summary-manifest>\" --stress-manifest \"<stress-summary-manifest>\" --field-report \"<field-report.json>\"",
        "",
        "## 4.1) Auditar CEN-04 isoladamente (matriz + drift_steps)",
        "",
        "python scripts/check_cen04_monitor_dpi_matrix.py --strict --field-report \"<field-report.json>\"",
        "",
        "## 5) Preencher pacote dedicado CEN-02 (operador)",
        "",
        "preencher `cen02.operator.template.md` e validar campos minimos com `cen02.minimum_checks.json`",
        "",
        "## 5.1) Partir do fixture realista CEN-02 (field-report)",
        "",
        "copiar `cen02.field_report.fixture.json` para o report consolidado e preencher refs reais por transicao",
        "",
        "## 6) Rodar preflight final de pre-abertura CEN-05",
        "",
        "python scripts/verify_cen05_preflight.py --strict --stress-manifest \"<stress-summary-manifest>\" --commands-file \"<commands-ready-md>\" --bundle-manifest \"<bundle-summary-manifest>\" --readiness-manifest \"<readiness-summary-manifest>\"",
        "",
        "## Referencias desta execucao",
        "",
        f"- qa_manifest: `{refs.get('qa_manifest', '')}`",
        f"- stress_manifest: `{refs.get('stress_manifest', '')}`",
        f"- readiness_manifest: `{refs.get('readiness_manifest', '')}`",
        f"- cen04_drift_worksheet: `{refs.get('cen04_drift_worksheet', '')}`",
        f"- cen02_operator_template: `{refs.get('cen02_operator_template', '')}`",
        f"- cen02_minimum_checks: `{refs.get('cen02_minimum_checks', '')}`",
        f"- cen02_field_report_fixture: `{refs.get('cen02_field_report_fixture', '')}`",
        f"- cen02_field_report_fixture_integrity: `{refs.get('cen02_field_report_fixture_integrity', '')}`",
        f"- cen04_matrix_audit_manifest: `{refs.get('cen04_matrix_audit_manifest', '')}`",
        f"- preopen_summary_md: `{refs.get('preopen_summary_md', '')}`",
        f"- preopen_summary_manifest: `{refs.get('preopen_summary_manifest', '')}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_checklist_md(path: Path) -> None:
    lines = [
        "# Field execution checklist (CEN-02..CEN-05)",
        "",
        "## CEN-02 Zoom/Escala",
        "- [ ] SUSPECT observado com evidence_ref",
        "- [ ] FROZEN observado com evidence_ref",
        "- [ ] RECALIBRATING observado com evidence_ref",
        "- [ ] retorno para STABLE com drift_px_max <= 3.0",
        "",
        "## CEN-03 OCR degradado",
        "- [ ] executar fluxo direto: baseline_check -> inject_degradation -> confirm_protection -> recover_signal",
        "- [ ] transicao STABLE->FROZEN|RECALIBRATING registrada",
        "- [ ] preservacao de lastStableAxis confirmada",
        "- [ ] transicao FROZEN|RECALIBRATING->STABLE registrada",
        "- [ ] incidente preenchido com 3 evidencias (screenshot/trace/log-snippet)",
        "- [ ] cada canal (hud/status_endpoint/trace_jsonl) contem expected/observed + evidence_ref",
        "- [ ] exemplo CEN-03-INC-EX-001/002 usado como referencia de preenchimento",
        "",
        "### CEN-03 Template operacional por incidente",
        "",
        "| incident_id | transition_stable_to_protection | transition_recovery_to_stable | symptom | suspected_root_cause | action_taken | result |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| CEN-03-INC-001 | [ ] | [ ] |  |  |  | pass|fail|blocked |",
        "",
        "| incident_id | channel | expected | observed | evidence_ref |",
        "| --- | --- | --- | --- | --- |",
        "| CEN-03-INC-001 | hud |  |  |  |",
        "| CEN-03-INC-001 | status_endpoint |  |  |  |",
        "| CEN-03-INC-001 | trace_jsonl |  |  |  |",
        "",
        "| incident_id | evidence_ref_1 | evidence_ref_2 | evidence_ref_3 |",
        "| --- | --- | --- | --- |",
        "| CEN-03-INC-001 |  |  |  |",
        "",
        "## CEN-04 Multi-monitor 100/125/150",
        "- [ ] usar versao curta abaixo para execucao de bancada",
        "- [ ] preencher worksheet dedicado `cen04_drift_worksheet.md` (drift por passo)",
        "",
        "### CEN-04 Execucao curta (bancada multi-monitor)",
        "",
        "| monitor_id | dpi_percent | transicao | bounds_ok | overlay_ok | drift_px | evidence_ref |",
        "| --- | ---: | --- | --- | --- | ---: | --- |",
        "| monitor-1 | 100 | baseline-open | [ ] | [ ] |  |  |",
        "| monitor-2 | 125 | move-to-monitor | [ ] | [ ] |  |  |",
        "| monitor-3 | 150 | move-to-monitor | [ ] | [ ] |  |  |",
        "",
        "| step_id | executed | timestamp_utc | monitor_id | dpi_percent | axis_status_before | axis_status_after | drift_px | evidence_ref |",
        "| --- | --- | --- | --- | ---: | --- | --- | ---: | --- |",
        "| open_window_on_baseline_monitor | [ ] |  | monitor-1 | 100 |  |  |  |  |",
        "| move_window_to_next_monitor | [ ] |  | monitor-2 | 125 |  |  |  |  |",
        "| minimize_window_on_target_monitor | [ ] |  | monitor-2 | 125 |  |  |  |  |",
        "| restore_window_on_target_monitor | [ ] |  | monitor-2 | 125 |  |  |  |  |",
        "| move_window_back_to_baseline_monitor | [ ] |  | monitor-3 | 150 |  |  |  |  |",
        "",
        "#### Criterios de aceite instantaneos (CEN-04)",
        "- [ ] cobertura DPI exata: 100/125/150",
        "- [ ] `bounds_ok` e `overlay_ok` marcados para todos os DPIs",
        "- [ ] `drift_px <= 3.0` em todas as linhas da matriz",
        "- [ ] cada linha com `evidence_ref` preenchido",
        "",
        "## CEN-05 Carga real",
        "- [ ] stress.csv anexado",
        "- [ ] summary.manifest.json do stress com gate.ok=true",
        "- [ ] thresholds validados (latencia/fps/backlog/publish/jitter)",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_cen04_drift_worksheet_md(path: Path) -> None:
    lines = [
        "# CEN-04 Drift Worksheet (Execucao fisica multi-monitor)",
        "",
        "## Artifacts naming padrao",
        "",
        "- session_slug: `ovr-stab-field-bundle-<YYYYMMDD-HHMMSS>`",
        "- scenario_id: `CEN-04`",
        "- monitor_tag: `monitor-<N>-dpi-<100|125|150>`",
        "- step_id: `open_window_on_baseline_monitor|move_window_to_next_monitor|minimize_window_on_target_monitor|restore_window_on_target_monitor|move_window_back_to_baseline_monitor`",
        "- evidence_ref (recomendado): `CEN-04/<monitor_tag>/<step_id>/<artifact_kind>-<UTC>.{png|jsonl|log}`",
        "- artifact_kind suportado: `screenshot|ocr_trace|overlay_log|window_bounds`",
        "",
        "## Matriz de medicao por monitor",
        "",
        "| monitor_id | dpi_percent | baseline_ref | final_ref | max_drift_px | pass_drift_lte_3px |",
        "| --- | ---: | --- | --- | ---: | --- |",
        "| monitor-1 | 100 |  |  |  | [ ] |",
        "| monitor-2 | 125 |  |  |  | [ ] |",
        "| monitor-3 | 150 |  |  |  | [ ] |",
        "",
        "## Drift por passo (preencher durante execucao fisica)",
        "",
        "| step_seq | step_id | timestamp_utc | monitor_id | dpi_percent | axis_status_before | axis_status_after | drift_px | bounds_ok | overlay_ok | evidence_ref | notes |",
        "| ---: | --- | --- | --- | ---: | --- | --- | ---: | --- | --- | --- | --- |",
        "| 1 | open_window_on_baseline_monitor |  | monitor-1 | 100 |  |  |  | [ ] | [ ] |  |  |",
        "| 2 | move_window_to_next_monitor |  | monitor-2 | 125 |  |  |  | [ ] | [ ] |  |  |",
        "| 3 | minimize_window_on_target_monitor |  | monitor-2 | 125 |  |  |  | [ ] | [ ] |  |  |",
        "| 4 | restore_window_on_target_monitor |  | monitor-2 | 125 |  |  |  | [ ] | [ ] |  |  |",
        "| 5 | move_window_back_to_baseline_monitor |  | monitor-3 | 150 |  |  |  | [ ] | [ ] |  |  |",
        "",
        "## Gate CEN-04",
        "",
        "- [ ] cobertura DPI concluida para 100/125/150",
        "- [ ] todas as linhas com `evidence_ref` preenchido no padrao definido",
        "- [ ] `bounds_ok` e `overlay_ok` marcados em todas as linhas",
        "- [ ] `drift_px <= 3.0` em todos os passos e monitores medidos",
        "",
        "## Pendencias manuais",
        "",
        "- [ ] consolidar refs finais no `field_execution.checklist.md`",
        "- [ ] anexar artefatos fisicos ao pacote de evidencia CEN-04",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_cen02_operator_template_md(path: Path) -> None:
    lines = [
        "# CEN-02 Operator Template (field-ready)",
        "",
        "Use este template durante a sessao real para preencher evidencias minimas de zoom/escala.",
        "",
        "## Contexto operacional",
        "- scenario_id: CEN-02",
        "- session_id: <preencher>",
        "- symbol: <preencher>",
        "- operator: <preencher>",
        "- started_at_utc: <preencher>",
        "",
        "## Checklist minimo pre-execucao",
        "- [ ] overlay com axis_status visivel (HUD ou endpoint)",
        "- [ ] captura de screenshot habilitada",
        "- [ ] captura de trace jsonl habilitada",
        "- [ ] marcador de logs para inicio da sessao",
        "",
        "## Passos de execucao",
        "| step_id | executed | timestamp_utc | action | axis_status_before | axis_status_after | stable_reached | evidence_ref | notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "| capturar_baseline_estavel_5s | [ ] |  |  |  |  | [ ] |  |  |",
        "| aplicar_zoom_in_progressivo | [ ] |  |  |  |  | [ ] |  |  |",
        "| aplicar_zoom_out_progressivo | [ ] |  |  |  |  | [ ] |  |  |",
        "| ajustar_escala_vertical_manual | [ ] |  |  |  |  | [ ] |  |  |",
        "| aguardar_retorno_stable_pos_evento | [ ] |  |  |  |  | [ ] |  |  |",
        "",
        "## Transicoes obrigatorias",
        "| transition_state | observed | event_timestamp_utc | pre_window_ref | post_window_ref | trigger_action | drift_px_peak | evidence_ref | screenshot_ref | trace_ref | status_endpoint_ref | expected_vs_observed |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        "| SUSPECT | [ ] |  |  |  |  |  |  |  |  |  |  |",
        "| FROZEN | [ ] |  |  |  |  |  |  |  |  |  |  |",
        "| RECALIBRATING | [ ] |  |  |  |  |  |  |  |  |  |  |",
        "",
        "## Criterios minimos de aceite",
        "- [ ] transicoes obrigatorias observadas com evidence_ref",
        "- [ ] retorno para STABLE confirmado no fim da sessao",
        "- [ ] drift_px_max apos retorno STABLE <= 3.0",
        "- [ ] nenhuma transicao marcada sem referencia rastreavel",
        "",
        "## Bloqueios",
        "- blocked_reason:",
        "- owner:",
        "- eta:",
        "- next_action:",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_cen02_minimum_checks_json(path: Path) -> None:
    payload = {
        "scenario_id": "CEN-02",
        "required_transitions": ["SUSPECT", "FROZEN", "RECALIBRATING"],
        "required_steps": [
            "capturar_baseline_estavel_5s",
            "aplicar_zoom_in_progressivo",
            "aplicar_zoom_out_progressivo",
            "ajustar_escala_vertical_manual",
            "aguardar_retorno_stable_pos_evento",
        ],
        "minimum_gates": {
            "required_transitions_count": {"op": ">=", "value": 3},
            "stable_return_required": {"op": "==", "value": 1},
            "drift_px_max_after_stable": {"op": "<=", "value": 3.0},
            "evidence_ref_coverage_ratio": {"op": "==", "value": 1.0},
        },
        "required_transition_evidence_fields": list(CEN02_REQUIRED_EVIDENCE_FIELDS),
        "required_fields": {
            "steps": [
                "step_id",
                "executed",
                "timestamp_utc",
                "action",
                "axis_status_before",
                "axis_status_after",
                "stable_reached",
                "evidence_ref",
            ],
            "transitions": [
                "transition_state",
                "observed",
                "event_timestamp_utc",
                "pre_window_ref",
                "post_window_ref",
                "trigger_action",
                "drift_px_peak",
                "evidence_ref",
                "screenshot_ref",
                "trace_ref",
                "status_endpoint_ref",
                "expected_vs_observed",
            ],
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _build_cen02_field_report_fixture_json(path: Path) -> Dict[str, Any]:
    transitions = [
        {
            "transition_state": "SUSPECT",
            "observed": True,
            "event_timestamp_utc": "2026-04-30T13:42:11Z",
            "pre_window_ref": "artifact://cen02/session-001/windows/suspect-pre.png",
            "post_window_ref": "artifact://cen02/session-001/windows/suspect-post.png",
            "trigger_action": "zoom-in-3-notches",
            "drift_px_peak": 2.4,
            "evidence_ref": "artifact://cen02/session-001/transitions/suspect.md",
            "screenshot_ref": "artifact://cen02/session-001/screenshots/suspect.png",
            "trace_ref": "artifact://cen02/session-001/trace/suspect.jsonl",
            "status_endpoint_ref": "artifact://cen02/session-001/status/suspect.json",
            "expected_vs_observed": "Esperado SUSPECT em zoom abrupto; observado SUSPECT por ~2s com preservacao de eixo.",
            "observed_at_utc": "2026-04-30T13:42:12Z",
        },
        {
            "transition_state": "FROZEN",
            "observed": True,
            "event_timestamp_utc": "2026-04-30T13:42:16Z",
            "pre_window_ref": "artifact://cen02/session-001/windows/frozen-pre.png",
            "post_window_ref": "artifact://cen02/session-001/windows/frozen-post.png",
            "trigger_action": "vertical-scale-drag-fast",
            "drift_px_peak": 3.0,
            "evidence_ref": "artifact://cen02/session-001/transitions/frozen.md",
            "screenshot_ref": "artifact://cen02/session-001/screenshots/frozen.png",
            "trace_ref": "artifact://cen02/session-001/trace/frozen.jsonl",
            "status_endpoint_ref": "artifact://cen02/session-001/status/frozen.json",
            "expected_vs_observed": "Esperado FROZEN durante ruido de escala; observado FROZEN com hold de lastStableAxis.",
            "freeze_duration_ms": 2400,
            "observed_at_utc": "2026-04-30T13:42:17Z",
        },
        {
            "transition_state": "RECALIBRATING",
            "observed": True,
            "event_timestamp_utc": "2026-04-30T13:42:21Z",
            "pre_window_ref": "artifact://cen02/session-001/windows/recal-pre.png",
            "post_window_ref": "artifact://cen02/session-001/windows/recal-post.png",
            "trigger_action": "zoom-out-2-notches",
            "drift_px_peak": 1.8,
            "evidence_ref": "artifact://cen02/session-001/transitions/recalibrating.md",
            "screenshot_ref": "artifact://cen02/session-001/screenshots/recalibrating.png",
            "trace_ref": "artifact://cen02/session-001/trace/recalibrating.jsonl",
            "status_endpoint_ref": "artifact://cen02/session-001/status/recalibrating.json",
            "expected_vs_observed": "Esperado RECALIBRATING e retorno para STABLE; observado settle em 3 ciclos.",
            "stable_return_ref": "artifact://cen02/session-001/screenshots/stable-return.png",
            "observed_at_utc": "2026-04-30T13:42:25Z",
        },
    ]
    fixture = {
        "scenarios": {
            "CEN-02": {
                "scenario_id": "CEN-02",
                "session_type": "manual-field-assisted",
                "session_id": "cen02-session-001",
                "symbol": "WINM26",
                "operator": "<preencher>",
                "started_at_utc": "2026-04-30T13:42:00Z",
                "completed_at_utc": "2026-04-30T13:42:31Z",
                "steps_executed": [
                    {
                        "step_id": "capturar_baseline_estavel_5s",
                        "executed": True,
                        "timestamp_utc": "2026-04-30T13:42:03Z",
                        "action": "captura baseline",
                        "axis_status_before": "STABLE",
                        "axis_status_after": "STABLE",
                        "stable_reached": True,
                        "evidence_ref": "artifact://cen02/session-001/steps/baseline.md",
                    },
                    {
                        "step_id": "aplicar_zoom_in_progressivo",
                        "executed": True,
                        "timestamp_utc": "2026-04-30T13:42:11Z",
                        "action": "zoom in progressivo",
                        "axis_status_before": "STABLE",
                        "axis_status_after": "SUSPECT",
                        "stable_reached": False,
                        "evidence_ref": "artifact://cen02/session-001/steps/zoom-in.md",
                    },
                    {
                        "step_id": "aplicar_zoom_out_progressivo",
                        "executed": True,
                        "timestamp_utc": "2026-04-30T13:42:21Z",
                        "action": "zoom out progressivo",
                        "axis_status_before": "FROZEN",
                        "axis_status_after": "RECALIBRATING",
                        "stable_reached": False,
                        "evidence_ref": "artifact://cen02/session-001/steps/zoom-out.md",
                    },
                    {
                        "step_id": "ajustar_escala_vertical_manual",
                        "executed": True,
                        "timestamp_utc": "2026-04-30T13:42:16Z",
                        "action": "escala vertical manual",
                        "axis_status_before": "SUSPECT",
                        "axis_status_after": "FROZEN",
                        "stable_reached": False,
                        "evidence_ref": "artifact://cen02/session-001/steps/vertical-scale.md",
                    },
                    {
                        "step_id": "aguardar_retorno_stable_pos_evento",
                        "executed": True,
                        "timestamp_utc": "2026-04-30T13:42:30Z",
                        "action": "aguardar settle",
                        "axis_status_before": "RECALIBRATING",
                        "axis_status_after": "STABLE",
                        "stable_reached": True,
                        "evidence_ref": "artifact://cen02/session-001/steps/stable-return.md",
                    },
                ],
                "transition_evidence": transitions,
                "drift_px_max_after_stable": 1.6,
                "stable_return_observed": True,
                "result": "pass",
            }
        }
    }
    path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return fixture


def _validate_cen02_fixture_integrity(payload: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = payload.get("scenarios", {})
    if not isinstance(scenarios, dict):
        return {"ok": False, "errors": ["fixture.scenarios_missing_or_invalid"], "checked_steps": 0, "checked_transitions": 0}
    cen02 = scenarios.get("CEN-02", {})
    if not isinstance(cen02, dict):
        return {"ok": False, "errors": ["fixture.CEN-02_missing_or_invalid"], "checked_steps": 0, "checked_transitions": 0}

    errors: List[str] = []
    steps = cen02.get("steps_executed", [])
    if not isinstance(steps, list):
        steps = []
        errors.append("fixture.CEN-02.steps_executed_missing_or_invalid")
    observed_step_ids = {str(step.get("step_id", "")).strip() for step in steps if isinstance(step, dict)}
    for required_step in (
        "capturar_baseline_estavel_5s",
        "aplicar_zoom_in_progressivo",
        "aplicar_zoom_out_progressivo",
        "ajustar_escala_vertical_manual",
        "aguardar_retorno_stable_pos_evento",
    ):
        if required_step not in observed_step_ids:
            errors.append(f"fixture.CEN-02.missing_step:{required_step}")

    transition_evidence = cen02.get("transition_evidence", [])
    if not isinstance(transition_evidence, list):
        return {
            "ok": False,
            "errors": errors + ["fixture.CEN-02.transition_evidence_missing_or_invalid"],
            "checked_steps": len(steps),
            "checked_transitions": 0,
        }

    transition_report = _validate_cen02_transition_evidence({"scenarios": {"CEN-02": {"transition_evidence": transition_evidence}}})
    if not bool(transition_report.get("ok")):
        errors.extend([f"fixture_integrity:{err}" for err in transition_report.get("errors", [])])
    if bool(cen02.get("stable_return_observed")) is not True:
        errors.append("fixture.CEN-02.stable_return_observed_not_true")
    try:
        drift_px_max = float(cen02.get("drift_px_max_after_stable", 999.0))
        if drift_px_max > 3.0:
            errors.append(f"fixture.CEN-02.drift_px_max_after_stable_gt_3:{drift_px_max}")
    except (TypeError, ValueError):
        errors.append("fixture.CEN-02.drift_px_max_after_stable_invalid")
    if str(cen02.get("result", "")).strip().lower() not in {"pass", "fail", "blocked"}:
        errors.append("fixture.CEN-02.result_invalid")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "checked_steps": len(steps),
        "checked_transitions": int(transition_report.get("checked_transitions", 0)),
    }


def _build_summary_md(path: Path, payload: Dict[str, Any]) -> None:
    qa = payload.get("qa", {})
    stress = payload.get("stress", {})
    readiness = payload.get("readiness", {})
    cen03_incident_packages_check = payload.get("cen03_incident_packages_check", {})
    cen02_transition_evidence_check = payload.get("cen02_transition_evidence_check", {})
    cen02_fixture_integrity_check = payload.get("cen02_fixture_integrity_check", {})
    cen04_field_matrix_check = payload.get("cen04_field_matrix_check", {})
    cen04_matrix_audit_check = payload.get("cen04_matrix_audit_check", {})
    cen05_field_report_check = payload.get("cen05_field_report_check", {})
    bundle_contract_check = payload.get("bundle_contract_check", {})
    lines = [
        "# OVR-STAB Field Bundle (CEN-02..CEN-05)",
        "",
        f"- strict_ok: `{int(bool(payload.get('strict_ok')) )}`",
        f"- qa_ok: `{int(bool(qa.get('ok')) )}`",
        f"- stress_ok: `{int(bool(stress.get('ok')) )}`",
        f"- readiness_ok: `{int(bool(readiness.get('ok')) )}`",
        "",
        "## Artifacts validation",
        "",
        f"- qa_artifacts_ok: `{int(bool(qa.get('artifacts_ok')) )}`",
        f"- stress_artifacts_ok: `{int(bool(stress.get('artifacts_ok')) )}`",
        f"- bundle_artifacts_ok: `{int(bool(payload.get('bundle_artifacts_ok')) )}`",
        f"- bundle_runner_logs_ok: `{int(bool(payload.get('bundle_runner_logs_ok')) )}`",
        f"- cen03_incident_packages_ok: `{int(bool(cen03_incident_packages_check.get('ok')) )}`",
        f"- cen03_incident_packages_checked: `{int(cen03_incident_packages_check.get('checked_incidents', 0))}`",
        f"- cen02_transition_evidence_ok: `{int(bool(cen02_transition_evidence_check.get('ok')) )}`",
        f"- cen02_transition_evidence_checked: `{int(cen02_transition_evidence_check.get('checked_transitions', 0))}`",
        f"- cen02_fixture_integrity_ok: `{int(bool(cen02_fixture_integrity_check.get('ok')) )}`",
        f"- cen02_fixture_integrity_steps_checked: `{int(cen02_fixture_integrity_check.get('checked_steps', 0))}`",
        f"- cen02_fixture_integrity_transitions_checked: `{int(cen02_fixture_integrity_check.get('checked_transitions', 0))}`",
        f"- cen04_field_matrix_ok: `{int(bool(cen04_field_matrix_check.get('ok')) )}`",
        f"- cen04_field_matrix_rows_checked: `{int(cen04_field_matrix_check.get('checked_rows', 0))}`",
        f"- cen04_field_matrix_steps_checked: `{int(cen04_field_matrix_check.get('checked_steps', 0))}`",
        f"- cen04_matrix_audit_ok: `{int(bool(cen04_matrix_audit_check.get('ok')) )}`",
        f"- cen05_field_report_ok: `{int(bool(cen05_field_report_check.get('ok')) )}`",
        f"- bundle_contract_ok: `{int(bool(bundle_contract_check.get('ok')) )}`",
        "",
        "## Manual gaps",
        "",
    ]
    manual_gaps = payload.get("manual_gaps", [])
    if manual_gaps:
        for gap in manual_gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"ovr-stab-field-bundle-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    steps: List[Dict[str, Any]] = []

    if not args.skip_stress:
        steps.append(
            _run(
                [
                    sys.executable,
                    "scripts/run_overlay_ws_stress_regression.py",
                    "--duration-scale",
                    str(max(0.05, float(args.duration_scale))),
                    "--frame-scale",
                    str(max(0.1, float(args.frame_scale))),
                ],
                out_dir,
                "step_01_stress",
            )
        )

    stress_dir = _latest_dir("overlay-ws-stress-regression")
    stress_manifest = stress_dir / "summary.manifest.json" if stress_dir else None

    if not args.skip_local_qa:
        qa_cmd = [
            sys.executable,
            "scripts/run_ovr_stab_qa_evidence.py",
            "--strict",
            "--mode",
            "field-ready",
            "--require-ovr",
            "OVR-STAB-QA-02",
            "--require-ovr",
            "OVR-STAB-QA-03",
            "--require-ovr",
            "OVR-STAB-QA-04",
            "--require-ovr",
            "OVR-STAB-QA-05",
            "--require-ovr",
            "OVR-STAB-OBS-09",
        ]
        if stress_manifest is not None:
            qa_cmd.extend(["--cen05-stress-manifest", str(stress_manifest)])
        steps.append(_run(qa_cmd, out_dir, "step_02_local_qa"))

    qa_dir = _latest_dir("ovr-stab-qa-evidence")
    qa_manifest = qa_dir / "summary.manifest.json" if qa_dir else None

    verify_cmd = [sys.executable, "scripts/verify_ovr_stab_g8_readiness.py"]
    if qa_manifest is not None:
        verify_cmd.extend(["--qa-manifest", str(qa_manifest)])
    if stress_manifest is not None:
        verify_cmd.extend(["--stress-manifest", str(stress_manifest)])
    if args.field_report is not None:
        verify_cmd.extend(["--field-report", str(args.field_report.resolve())])
    steps.append(_run(verify_cmd, out_dir, "step_03_readiness"))
    if args.field_report is not None:
        steps.append(
            _run(
                [
                    sys.executable,
                    "scripts/check_cen04_monitor_dpi_matrix.py",
                    "--field-report",
                    str(args.field_report.resolve()),
                    "--out-dir",
                    str(out_dir / "cen04-matrix-audit"),
                ],
                out_dir,
                "step_04_cen04_matrix_audit",
            )
        )

    readiness_dir = _latest_dir("ovr-stab-g8-readiness")
    readiness_manifest = readiness_dir / "summary.manifest.json" if readiness_dir else None
    preopen_cmd = [sys.executable, "scripts/verify_cen05_preflight.py"]
    if stress_manifest is not None:
        preopen_cmd.extend(["--stress-manifest", str(stress_manifest)])
    if readiness_manifest is not None:
        preopen_cmd.extend(["--readiness-manifest", str(readiness_manifest)])
    preopen_cmd.extend(["--bundle-manifest", str(out_dir / "summary.manifest.json")])
    preopen_cmd.extend(["--commands-file", str(out_dir / "commands.ready.md")])
    preopen_cmd.extend(["--out-dir", str(out_dir / "preopen")])
    steps.append(_run(preopen_cmd, out_dir, "step_05_preopen"))

    qa_artifacts_check = _validate_required_files(qa_dir, EXPECTED_QA_FILES) if qa_dir else {"ok": False, "missing": ["qa_dir_not_found"]}
    stress_artifacts_check = (
        _validate_required_files(stress_dir, EXPECTED_STRESS_FILES)
        if stress_dir
        else {"ok": False, "missing": ["stress_dir_not_found"]}
    )

    commands_md = out_dir / "commands.ready.md"
    preopen_md = out_dir / "preopen.md"
    checklist_md = out_dir / "field_execution.checklist.md"
    cen04_worksheet_md = out_dir / "cen04_drift_worksheet.md"
    cen02_template_md = out_dir / "cen02.operator.template.md"
    cen02_min_checks_json = out_dir / "cen02.minimum_checks.json"
    cen02_field_report_fixture_json = out_dir / "cen02.field_report.fixture.json"
    cen02_field_report_fixture_integrity_json = out_dir / "cen02.field_report.fixture.integrity.json"
    summary_md = out_dir / "summary.md"
    summary_manifest = out_dir / "summary.manifest.json"
    _build_cen04_drift_worksheet_md(cen04_worksheet_md)
    _build_cen02_operator_template_md(cen02_template_md)
    _build_cen02_minimum_checks_json(cen02_min_checks_json)
    cen02_fixture_payload = _build_cen02_field_report_fixture_json(cen02_field_report_fixture_json)
    cen02_fixture_integrity_check = _validate_cen02_fixture_integrity(cen02_fixture_payload)
    cen02_field_report_fixture_integrity_json.write_text(
        json.dumps(cen02_fixture_integrity_check, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _build_commands_md(
        commands_md,
        {
            "qa_manifest": str(qa_manifest) if qa_manifest else "",
            "stress_manifest": str(stress_manifest) if stress_manifest else "",
            "readiness_manifest": str(readiness_manifest) if readiness_manifest else "",
            "cen04_drift_worksheet": str(cen04_worksheet_md),
            "cen02_operator_template": str(cen02_template_md),
            "cen02_minimum_checks": str(cen02_min_checks_json),
            "cen02_field_report_fixture": str(cen02_field_report_fixture_json),
            "cen02_field_report_fixture_integrity": str(cen02_field_report_fixture_integrity_json),
            "cen04_matrix_audit_manifest": str(out_dir / "cen04-matrix-audit" / "summary.manifest.json"),
            "preopen_summary_md": str(out_dir / "preopen" / "summary.md"),
            "preopen_summary_manifest": str(out_dir / "preopen" / "summary.manifest.json"),
        },
    )
    _build_checklist_md(checklist_md)

    readiness_payload = _load_json(readiness_manifest)
    preopen_summary_md = out_dir / "preopen" / "summary.md"
    preopen_summary_manifest = out_dir / "preopen" / "summary.manifest.json"
    preopen_payload = _load_json(preopen_summary_manifest)
    if preopen_summary_md.exists():
        preopen_md.write_text(preopen_summary_md.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        preopen_md.write_text("# CEN-05 preopen\n\n- sem saida de preflight\n", encoding="utf-8")
    field_report_payload = _load_json(args.field_report.resolve()) if args.field_report is not None else {}
    cen03_incident_check = (
        validate_cen03_incident_packages(field_report_payload)
        if args.field_report is not None
        else {"ok": True, "checked_incidents": 0, "errors": ["field_report_not_provided"], "incident_evidence_index": {}}
    )
    cen03_incident_index = (
        build_incident_evidence_index(field_report_payload)
        if args.field_report is not None
        else {"ok": True, "checked_incidents": 0, "index": {}, "errors": ["field_report_not_provided"]}
    )
    cen02_transition_check = (
        _validate_cen02_transition_evidence(field_report_payload)
        if args.field_report is not None
        else {"ok": True, "checked_transitions": 0, "errors": ["field_report_not_provided"]}
    )
    cen04_field_matrix_check = (
        _validate_cen04_field_matrix(field_report_payload)
        if args.field_report is not None
        else {"ok": True, "checked_rows": 0, "checked_steps": 0, "errors": ["field_report_not_provided"]}
    )
    cen05_field_report_check = (
        _validate_cen05_field_report(field_report_payload)
        if args.field_report is not None
        else {"ok": True, "checked": 0, "errors": ["field_report_not_provided"]}
    )
    cen04_matrix_audit_manifest = _resolve_cen04_audit_manifest(steps, out_dir)
    cen04_matrix_audit_payload = _load_json(cen04_matrix_audit_manifest)
    cen04_matrix_audit_check = (
        {
            "ok": bool(cen04_matrix_audit_payload.get("ok", False)),
            "issues": list(cen04_matrix_audit_payload.get("issues", [])),
            "manifest": str(cen04_matrix_audit_manifest),
        }
        if cen04_matrix_audit_payload
        else {
            "ok": bool(args.field_report is None or _step_ok(steps, "step_04_cen04_matrix_audit")),
            "issues": [] if args.field_report is None else ["CEN-04.audit_manifest_missing_or_invalid"],
            "manifest": str(cen04_matrix_audit_manifest) if cen04_matrix_audit_manifest else "",
        }
    )
    scenario_results = readiness_payload.get("scenario_results", []) if isinstance(readiness_payload, dict) else []
    manual_gaps = []
    for scenario in scenario_results:
        if not isinstance(scenario, dict):
            continue
        if str(scenario.get("scenario_id", "")) not in {"CEN-02", "CEN-03", "CEN-04", "CEN-05"}:
            continue
        if str(scenario.get("status", "")) != "PASS":
            manual_gaps.append(f"{scenario.get('scenario_id')}: campo pendente/nao aprovado")
    if not manual_gaps:
        manual_gaps.append("Sem lacunas manuais para CEN-02..CEN-05 nesta execucao.")
    if not bool(cen03_incident_check.get("ok", False)):
        for err in cen03_incident_check.get("errors", []):
            manual_gaps.append(
                f"CEN-03 incidente: {_ensure_actionable(str(err), 'corrigir incident_packages e repetir validacao readiness/bundle')}"
            )
    for incident_id, incident_info in sorted(cen03_incident_index.get("index", {}).items()):
        refs = incident_info.get("evidence_ref", [])
        channels = incident_info.get("channels_with_evidence", [])
        manual_gaps.append(
            f"CEN-03 incidente consolidado {incident_id}: evidencias={len(refs)} canais={','.join(channels)}"
        )
    if not bool(cen02_transition_check.get("ok", False)):
        for err in cen02_transition_check.get("errors", []):
            manual_gaps.append(f"CEN-02 transicao: {err}")
    if not bool(cen04_field_matrix_check.get("ok", False)):
        for err in cen04_field_matrix_check.get("errors", []):
            manual_gaps.append(f"CEN-04 matriz: {err}")
    if not bool(cen05_field_report_check.get("ok", False)):
        for err in cen05_field_report_check.get("errors", []):
            manual_gaps.append(f"CEN-05 field-report: {err}")
    if not bool(cen04_matrix_audit_check.get("ok", False)):
        for issue in cen04_matrix_audit_check.get("issues", []):
            manual_gaps.append(f"CEN-04 auditoria isolada: {issue}")

    qa_required = not bool(args.skip_local_qa)
    stress_required = not bool(args.skip_stress)

    payload: Dict[str, Any] = {
        "runner": "run_ovr_stab_field_bundle.py",
        "contract_version": FIELD_BUNDLE_CONTRACT_VERSION,
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps": steps,
        "qa": {
            "dir": str(qa_dir) if qa_dir else "",
            "manifest": str(qa_manifest) if qa_manifest else "",
            "required": qa_required,
            "ok": bool(qa_manifest and _load_json(qa_manifest).get("strict_ok", False)),
            "artifacts_ok": bool(qa_artifacts_check.get("ok", False)),
            "artifacts_check": qa_artifacts_check,
        },
        "stress": {
            "dir": str(stress_dir) if stress_dir else "",
            "manifest": str(stress_manifest) if stress_manifest else "",
            "required": stress_required,
            "ok": bool(stress_manifest and _load_json(stress_manifest).get("overall_ok", False)),
            "artifacts_ok": bool(stress_artifacts_check.get("ok", False)),
            "artifacts_check": stress_artifacts_check,
        },
        "readiness": {
            "dir": str(readiness_dir) if readiness_dir else "",
            "manifest": str(readiness_manifest) if readiness_manifest else "",
            "ok": bool(readiness_manifest and _load_json(readiness_manifest).get("g8_ready", False)),
        },
        "preopen": {
            "summary_md": str(preopen_summary_md),
            "summary_manifest": str(preopen_summary_manifest),
            "ok": bool(preopen_payload.get("preflight_ok", False)),
            "messages": preopen_payload.get("operational_messages", []),
        },
        "cen03_incident_packages_check": cen03_incident_check,
        "cen03_incident_evidence_index": cen03_incident_index,
        "cen02_transition_evidence_check": cen02_transition_check,
        "cen02_fixture_integrity_check": cen02_fixture_integrity_check,
        "cen04_field_matrix_check": cen04_field_matrix_check,
        "cen04_matrix_audit_check": cen04_matrix_audit_check,
        "cen05_field_report_check": cen05_field_report_check,
        "manual_gaps": manual_gaps,
        "artifacts": {
            "summary_md": str(summary_md),
            "summary_manifest": str(summary_manifest),
            "field_execution_checklist": str(checklist_md),
            "cen04_drift_worksheet": str(cen04_worksheet_md),
            "cen02_operator_template": str(cen02_template_md),
            "cen02_minimum_checks": str(cen02_min_checks_json),
            "cen02_field_report_fixture": str(cen02_field_report_fixture_json),
            "cen02_field_report_fixture_integrity": str(cen02_field_report_fixture_integrity_json),
            "commands_ready_md": str(commands_md),
            "preopen_md": str(preopen_md),
            "cen04_matrix_audit_manifest": str(cen04_matrix_audit_manifest) if cen04_matrix_audit_manifest else "",
        },
        "report_contract": {
            "preopen_required_fields": ["preopen_status_code", "checks", "next_actions", "operational_messages"],
            "scenario_manual_gaps_required_prefixes": ["CEN-02", "CEN-03", "CEN-04", "CEN-05"],
        },
    }
    _build_summary_md(summary_md, payload)
    summary_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    bundle_artifacts_check = _validate_required_files(out_dir, EXPECTED_BUNDLE_FILES)
    bundle_runner_logs_check = _validate_runner_logs(out_dir, ("step_03_readiness", "step_05_preopen"))
    bundle_contract_check = _validate_bundle_contract(out_dir)
    preopen_contract_check = _validate_preopen_contract(preopen_payload)
    payload["bundle_artifacts_ok"] = bool(bundle_artifacts_check.get("ok", False))
    payload["bundle_artifacts_check"] = bundle_artifacts_check
    payload["bundle_runner_logs_ok"] = bool(bundle_runner_logs_check.get("ok", False))
    payload["bundle_runner_logs_check"] = bundle_runner_logs_check
    payload["bundle_contract_ok"] = bool(bundle_contract_check.get("ok", False))
    payload["bundle_contract_check"] = bundle_contract_check
    payload["preopen_contract_ok"] = bool(preopen_contract_check.get("ok", False))
    payload["preopen_contract_check"] = preopen_contract_check
    qa_gate_ok = bool((not qa_required) or (payload["qa"]["ok"] and payload["qa"]["artifacts_ok"]))
    stress_gate_ok = bool((not stress_required) or (payload["stress"]["ok"] and payload["stress"]["artifacts_ok"]))
    strict_gate_diagnostics = {
        "qa_gate_ok": qa_gate_ok,
        "stress_gate_ok": stress_gate_ok,
        "readiness_ok": bool(payload["readiness"]["ok"]),
        "preopen_ok": bool(payload["preopen"]["ok"]),
        "bundle_artifacts_ok": bool(payload["bundle_artifacts_ok"]),
        "bundle_runner_logs_ok": bool(payload["bundle_runner_logs_ok"]),
        "bundle_contract_ok": bool(payload["bundle_contract_ok"]),
        "preopen_contract_ok": bool(payload["preopen_contract_ok"]),
        "cen03_incident_packages_ok": bool(payload["cen03_incident_packages_check"]["ok"]),
        "cen02_transition_evidence_ok": bool(payload["cen02_transition_evidence_check"]["ok"]),
        "cen02_fixture_integrity_ok": bool(payload["cen02_fixture_integrity_check"]["ok"]),
        "cen04_field_matrix_ok": bool(payload["cen04_field_matrix_check"]["ok"]),
        "cen04_matrix_audit_ok": bool(payload["cen04_matrix_audit_check"]["ok"]),
        "cen05_field_report_ok": bool(payload["cen05_field_report_check"]["ok"]),
    }
    payload["strict_gate_diagnostics"] = strict_gate_diagnostics
    payload["strict_ok"] = all(strict_gate_diagnostics.values())
    _build_summary_md(summary_md, payload)
    summary_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    print(f"Wrote: {checklist_md}")
    print(f"Wrote: {cen04_worksheet_md}")
    print(f"Wrote: {cen02_template_md}")
    print(f"Wrote: {cen02_min_checks_json}")
    print(f"Wrote: {cen02_field_report_fixture_json}")
    print(f"Wrote: {cen02_field_report_fixture_integrity_json}")
    print(f"Wrote: {commands_md}")
    print(f"Wrote: {preopen_md}")

    if args.strict and not bool(payload["strict_ok"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
