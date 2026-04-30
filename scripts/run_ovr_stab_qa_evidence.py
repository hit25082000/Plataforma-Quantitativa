#!/usr/bin/env python3
"""
Runner local para evidências mínimas de QA/observabilidade do OCR overlay.

Escopo:
- Executa suítes de testes unitários/mocks que não dependem de sessão real Profit.
- Consolida artefatos em summary.csv, summary.md e summary.manifest.json.
- Classifica cobertura parcial de OVR-STAB-QA-01..05 e OVR-STAB-OBS-09.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_SCHEMA_VERSION = "1.0.0"
TRACE_SCHEMA_PATH = ROOT / "docs" / "contracts" / "ocr-overlay-trace-v1.json"
TRACE_FIXTURE_PATH = ROOT / "docs" / "contracts" / "fixtures" / "ocr-overlay-trace-demo.jsonl"
SCENARIO_BY_OVR = {
    "OVR-STAB-QA-01": "CEN-01-parado",
    "OVR-STAB-QA-02": "CEN-02-zoom-escala",
    "OVR-STAB-QA-03": "CEN-03-ocr-ruim",
    "OVR-STAB-QA-04": "CEN-04-multi-monitor-dpi",
    "OVR-STAB-QA-05": "CEN-05-carga",
    "OVR-STAB-OBS-09": "CEN-OBS-09-explicabilidade",
}

DEFAULT_SUITES = [
    {
        "id": "qa_axis_overlay_contract",
        "ovr": ["OVR-STAB-QA-01", "OVR-STAB-QA-03", "OVR-STAB-OBS-09"],
        "cmd": [sys.executable, "-m", "unittest", "distributor.tests.test_profit_ocr_service"],
    },
    {
        "id": "qa_overlay_proxy_endpoints",
        "ovr": ["OVR-STAB-QA-02", "OVR-STAB-OBS-09"],
        "cmd": [sys.executable, "-m", "unittest", "distributor.tests.test_websocket_vp_overlay_endpoints"],
    },
    {
        "id": "qa_enrich_overlay_axis_health",
        "ovr": ["OVR-STAB-QA-01", "OVR-STAB-QA-05", "OVR-STAB-OBS-09"],
        "cmd": [sys.executable, "-m", "unittest", "distributor.tests.test_vp_ocr_enrich"],
    },
    {
        "id": "qa_overlay_ws_stress_regression_harness",
        "ovr": ["OVR-STAB-QA-05", "OVR-STAB-OBS-09"],
        "cmd": [sys.executable, "-m", "unittest", "distributor.tests.test_run_overlay_ws_stress_regression"],
    },
]

OVR_TARGETS = ["OVR-STAB-QA-01", "OVR-STAB-QA-02", "OVR-STAB-QA-03", "OVR-STAB-QA-04", "OVR-STAB-QA-05", "OVR-STAB-OBS-09"]
ARTIFACT_STRUCTURE_REQUIRED_FILES = [
    "summary.csv",
    "summary.md",
    "target_protocols.manifest.json",
    "target_protocols.checklist.md",
]
ARTIFACT_STRUCTURE_REQUIRED_FILES_FINAL = [*ARTIFACT_STRUCTURE_REQUIRED_FILES, "summary.manifest.json"]
CEN04_MONITOR_DPI_MATRIX = [
    {"monitor_id": "monitor-1", "dpi_percent": 100, "transition": "baseline-open"},
    {"monitor_id": "monitor-2", "dpi_percent": 125, "transition": "move-to-monitor"},
    {"monitor_id": "monitor-3", "dpi_percent": 150, "transition": "move-to-monitor"},
]
REQUIRED_CEN04_MONITOR_FIELDS = ("monitor_id", "dpi_percent", "transition")
CEN04_ALLOWED_TRANSITIONS = {"baseline-open", "move-to-monitor"}
CEN04_REPRO_STEPS = [
    "open_window_on_baseline_monitor",
    "move_window_to_next_monitor",
    "minimize_window_on_target_monitor",
    "restore_window_on_target_monitor",
    "move_window_back_to_baseline_monitor",
]
DRIFT_COLLECTION_REQUIRED_FIELDS = [
    "scenario_id",
    "step_id",
    "monitor_id",
    "dpi_percent",
    "timestamp_utc",
    "axis_status_before",
    "axis_status_after",
    "drift_px",
    "drift_band",
    "evidence_ref",
]
CEN03_INJECTION_PROTOCOL_STEPS = [
    "capture_baseline_axis_stable",
    "apply_ocr_degradation_injection",
    "observe_status_transition_to_frozen_or_recalibrating",
    "verify_last_stable_axis_preserved",
    "remove_degradation_and_watch_recovery_to_stable",
]
CEN03_OPERATOR_DIRECT_FLOW = [
    {
        "step_id": "baseline_check",
        "operator_action": "Confirmar axis_status=STABLE por 5s",
        "expected_result": "baseline sem jitter e confidence estavel",
        "evidence_required": "screenshot + trace_ref",
    },
    {
        "step_id": "inject_degradation",
        "operator_action": "Aplicar oclusao parcial no eixo ou reduzir contraste",
        "expected_result": "queda de confidence/residual_px crescente",
        "evidence_required": "video_ref ou screenshot sequencial",
    },
    {
        "step_id": "confirm_protection",
        "operator_action": "Acompanhar transicao para FROZEN/RECALIBRATING",
        "expected_result": "last_stable_axis preservado sem salto abrupto",
        "evidence_required": "trace_ref + status_endpoint_ref",
    },
    {
        "step_id": "recover_signal",
        "operator_action": "Remover degradacao e aguardar recuperacao",
        "expected_result": "retorno para STABLE com drift controlado",
        "evidence_required": "screenshot pos-recuperacao + trace_ref",
    },
]
CEN03_REQUIRED_SIGNALS = {
    "hud": [
        "axis_status",
        "axis_source",
        "pending_frames",
        "bad_frames",
        "confidence",
        "residual_px",
    ],
    "status_endpoint": [
        "status",
        "axis_status",
        "axis_source",
        "bad_frames",
        "pending_count",
        "confidence",
        "residual_px",
        "last_frame",
    ],
    "trace_jsonl": [
        "timestamp_utc",
        "frame_seq",
        "axis_status",
        "axis_source",
        "bad_frames",
        "pending_count",
        "confidence",
        "residual_px",
        "max_error_px",
        "last_stable_axis",
    ],
}
CEN03_REQUIRED_TRANSITIONS = [
    "STABLE->FROZEN|RECALIBRATING",
    "FROZEN|RECALIBRATING->STABLE",
]
CEN03_INCIDENT_MIN_EVIDENCE = {
    "min_evidence_refs": 3,
    "required_artifact_kinds": ["screenshot", "trace", "log-snippet"],
    "required_channels_with_expected_vs_observed": ["hud", "status_endpoint", "trace_jsonl"],
    "required_incident_fields": [
        "incident_id",
        "scenario_id",
        "injection_method",
        "injection_window_utc",
        "symptom",
        "observed_state_transitions",
        "expected_signals_by_channel",
        "observed_signals_by_channel",
        "suspected_root_cause",
        "action_taken",
        "result",
        "evidence_ref",
    ],
}
CEN03_EVIDENCE_TEMPLATE_REQUIRED_FIELDS = [
    "incident_id",
    "scenario_id",
    "injection_method",
    "injection_window_utc",
    "symptom",
    "observed_state_transitions",
    "expected_signals_by_channel",
    "observed_signals_by_channel",
    "suspected_root_cause",
    "action_taken",
    "result",
    "evidence_ref",
]
CEN03_INCIDENT_EXAMPLES = [
    {
        "incident_id": "CEN-03-INC-EX-001",
        "scenario_id": "CEN-03",
        "symptom": "linhas POC/VAL congeladas durante oclusao parcial",
        "suspected_root_cause": "OCR sem labels validas por contraste baixo temporario",
        "action_taken": "mantido FROZEN ate remocao da oclusao",
        "result": "pass",
        "evidence_ref": [
            "artifact://ovr-stab-CEN-03-screenshot-20260430T174500Z.png",
            "artifact://ovr-stab-CEN-03-trace-20260430T174500Z.jsonl",
            "artifact://ovr-stab-CEN-03-log-snippet-20260430T174500Z.txt",
        ],
    },
    {
        "incident_id": "CEN-03-INC-EX-002",
        "scenario_id": "CEN-03",
        "symptom": "recuperacao lenta para STABLE apos degradacao removida",
        "suspected_root_cause": "pending_count alto durante janela de revalidacao",
        "action_taken": "coleta adicional de 10s e comparacao expected_vs_observed",
        "result": "fail",
        "evidence_ref": [
            "artifact://ovr-stab-CEN-03-screenshot-20260430T180000Z.png",
            "artifact://ovr-stab-CEN-03-trace-20260430T180000Z.jsonl",
            "artifact://ovr-stab-CEN-03-log-snippet-20260430T180000Z.txt",
        ],
    },
]
CEN02_REQUIRED_TRANSITIONS = ["SUSPECT", "FROZEN", "RECALIBRATING"]
CEN02_TRANSITION_REQUIRED_FIELDS = [
    "transition_state",
    "observed",
    "event_timestamp_utc",
    "pre_window_ref",
    "post_window_ref",
    "trigger_action",
    "drift_px_peak",
    "evidence_ref",
]
CEN02_STEP_REQUIRED_FIELDS = [
    "step_id",
    "executed",
    "timestamp_utc",
    "action",
    "axis_status_before",
    "axis_status_after",
    "stable_reached",
    "evidence_ref",
]
CEN02_QUALITY_GATES = {
    "required_transitions_count": {"op": ">=", "value": 3},
    "stable_return_required": {"op": "==", "value": 1},
    "drift_px_max_after_stable": {"op": "<=", "value": 3.0},
    "evidence_ref_coverage_ratio": {"op": "==", "value": 1.0},
}
TRACE_REQUIRED_SESSION_FIELDS = [
    "event",
    "event_id",
    "session_id",
    "started_at",
]
TRACE_REQUIRED_FRAME_FIELDS = [
    "event",
    "event_id",
    "session_id",
    "seq",
    "frame_seq",
    "ts",
    "timestamp_utc",
    "status",
    "render_indicators",
    "status_transition",
]
TRACE_REQUIRED_RENDER_INDICATOR_FIELDS = [
    "line_count_total",
    "line_count_visible",
    "line_count_out_of_bounds",
]
TRACE_REQUIRED_STATUS_TRANSITION_FIELDS = [
    "from",
    "to",
    "changed",
]
TRACE_REQUIRED_BY_EVENT = {
    "session_start": TRACE_REQUIRED_SESSION_FIELDS,
    "frame": TRACE_REQUIRED_FRAME_FIELDS,
}
CEN02_EXECUTION_STEPS = [
    "capturar_baseline_estavel_5s",
    "aplicar_zoom_in_progressivo",
    "aplicar_zoom_out_progressivo",
    "ajustar_escala_vertical_manual",
    "aguardar_retorno_stable_pos_evento",
]
CEN05_LOAD_THRESHOLD_CONTRACT = {
    "queue_max": {"op": "<=", "value": 1},
    "backlog_growth_ratio": {"op": "<=", "value": 1.5},
    "latency_p95_ms": {"op": "<=", "value": 60.0},
    "latency_p99_ms": {"op": "<=", "value": 120.0},
    "consumer_fps": {"op": ">=", "value": 90.0},
    "publish_rate_floor_ratio": {"op": ">=", "value": 0.75},
    "publish_rate_overshoot_ratio": {"op": "<=", "value": 1.15},
    "publish_interval_jitter_cv": {"op": "<=", "value": 0.35},
}

TARGET_PROTOCOLS: Dict[str, Dict[str, Any]] = {
    "OVR-STAB-AUD-04": {
        "title": "Coleta 60s com grafico parado",
        "objective": "Isolar jitter em cenario estavel e atribuir causa observavel por sinais de eixo/render.",
        "acceptance_criteria": [
            "captura de 60s registrada com resumo de variacao por frame",
            "manifesto inclui sinalizacao de causa provavel: label/regressao/render",
            "evidencia organizada em json/md/csv com links para logs da sessao",
        ],
        "manual_dependencies": [
            "sessao Profit/replay com grafico parado por 60s",
        ],
    },
    "OVR-STAB-AUD-05": {
        "title": "Coleta com mudanca de zoom/escala",
        "objective": "Documentar transicoes de estado durante troca de escala e validar comportamento de congelamento/recalibracao.",
        "acceptance_criteria": [
            "eventos de zoom/escala anotados com timestamp e descricao",
            "transicoes SUSPECT/FROZEN/RECALIBRATING aparecem na evidencia",
            "trace aponta janela pre-evento e pos-evento com correlacao",
        ],
        "manual_dependencies": [
            "acao manual de zoom/escala no grafico",
        ],
    },
    "OVR-STAB-QA-03": {
        "title": "Protocolo CEN-03 de OCR degradado",
        "objective": "Padronizar a injeção/observação de OCR ruim com explicabilidade fim-a-fim em HUD/status/trace.",
        "acceptance_criteria": [
            "protocolo segue passos de injeção e recuperação do CEN-03 sem ambiguidade",
            "sinais esperados por canal (HUD, status endpoint, trace jsonl) são mapeados e conferidos",
            "evidência registra sintomas, causa provável e ação aplicada com referência objetiva",
        ],
        "manual_dependencies": [
            "sessão Profit/replay com capacidade de induzir OCR degradado",
        ],
    },
    "OVR-STAB-QA-04": {
        "title": "Protocolo multi-monitor DPI 100/125/150",
        "objective": "Garantir alinhamento de bounds/overlay ao mover janela entre monitores com DPI distintos.",
        "acceptance_criteria": [
            "execucao registrada para 100%, 125% e 150%",
            "cada monitor possui status pass/fail e anexo de evidencia",
            "manifesto inclui observacoes sobre drift e offset em pixels",
        ],
        "manual_dependencies": [
            "ambiente com ao menos dois monitores e perfis DPI 100/125/150",
        ],
    },
    "OVR-STAB-QA-05": {
        "title": "Protocolo de carga real CEN-05",
        "objective": "Comprovar estabilidade simultanea de backlog, taxa de publish e FPS efetivo sob carga.",
        "acceptance_criteria": [
            "stress.csv e summary.manifest.json anexados com resultado por cenario",
            "thresholds de backlog/publish/FPS avaliados de forma objetiva e rastreavel",
            "nenhum cenario com backlog crescente ou jitter persistente de publish",
        ],
        "manual_dependencies": [
            "execucao em horario de mercado ou replay representativo de alta carga",
        ],
    },
    "OVR-STAB-OBS-09": {
        "title": "Checklist estruturado de explicabilidade",
        "objective": "Padronizar evidencias para explicar falhas sem depender de memoria operacional.",
        "acceptance_criteria": [
            "matriz sintoma->causa->sinal preenchida para cada incidente",
            "campo de confianca da hipotese e proximo passo obrigatorios",
            "bundle final possui md/json com referencias cruzadas",
        ],
        "manual_dependencies": [],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--stop-on-fail", action="store_true", default=False)
    parser.add_argument("--mode", choices=["local", "field-ready"], default="local")
    parser.add_argument("--strict", action="store_true", default=False)
    parser.add_argument("--require-ovr", action="append", default=[])
    parser.add_argument("--cen05-stress-manifest", type=Path, default=None)
    return parser.parse_args()


def run_suite(suite: Dict[str, object], out_dir: Path) -> Dict[str, object]:
    suite_id = str(suite["id"])
    cmd = [str(item) for item in suite["cmd"]]  # type: ignore[index]
    stdout_log = out_dir / f"{suite_id}.stdout.log"
    stderr_log = out_dir / f"{suite_id}.stderr.log"
    started = time.time()
    with stdout_log.open("w", encoding="utf-8") as out_f, stderr_log.open("w", encoding="utf-8") as err_f:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=out_f, stderr=err_f, check=False, shell=False)
    elapsed = round(time.time() - started, 3)
    ok = int(proc.returncode) == 0
    return {
        "id": suite_id,
        "ovr": list(suite["ovr"]),  # type: ignore[index]
        "ok": ok,
        "exit_code": int(proc.returncode),
        "elapsed_s": elapsed,
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "command": cmd,
    }


def build_ovr_status(results: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    status: Dict[str, Dict[str, object]] = {}
    for ovr_id in OVR_TARGETS:
        related = [r for r in results if ovr_id in r["ovr"]]  # type: ignore[operator]
        if not related:
            status[ovr_id] = {"state": "not-covered", "coverage": "none", "suites": []}
            continue
        all_ok = all(bool(r["ok"]) for r in related)
        suite_ids = [str(r["id"]) for r in related]
        status[ovr_id] = {
            "state": "partial-done" if all_ok else "partial-blocked",
            "coverage": "local-tests-mocked",
            "suites": suite_ids,
        }
    return status


def write_summary_csv(path: Path, results: List[Dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["suite_id", "ok", "exit_code", "elapsed_s", "ovr_ids", "stdout_log", "stderr_log"])
        for row in results:
            writer.writerow(
                [
                    row["id"],
                    int(bool(row["ok"])),
                    row["exit_code"],
                    row["elapsed_s"],
                    ",".join(str(item) for item in row["ovr"]),  # type: ignore[union-attr]
                    row["stdout_log"],
                    row["stderr_log"],
                ]
            )


def write_summary_md(path: Path, results: List[Dict[str, object]], ovr_status: Dict[str, Dict[str, object]], overall_ok: bool) -> None:
    lines: List[str] = []
    lines.append("# OVR STAB QA Evidence (Local)")
    lines.append("")
    lines.append(f"- overall_ok: `{int(overall_ok)}`")
    lines.append(f"- suites: `{len(results)}`")
    lines.append("")
    lines.append("## Suites")
    lines.append("")
    lines.append("| suite | ok | exit_code | elapsed_s | OVRs |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for row in results:
        lines.append(
            f"| {row['id']} | {int(bool(row['ok']))} | {row['exit_code']} | {row['elapsed_s']} | {','.join(str(item) for item in row['ovr'])} |"
        )
    lines.append("")
    lines.append("## OVR Status (partial/local)")
    lines.append("")
    lines.append("| OVR | state | coverage | suites |")
    lines.append("| --- | --- | --- | --- |")
    for ovr_id in OVR_TARGETS:
        entry = ovr_status[ovr_id]
        lines.append(f"| {ovr_id} | {entry['state']} | {entry['coverage']} | {','.join(entry['suites'])} |")
    lines.append("")
    lines.append("## CEN-05 Threshold Contract")
    lines.append("")
    lines.append("| metric | operator | threshold |")
    lines.append("| --- | --- | ---: |")
    for metric, rule in CEN05_LOAD_THRESHOLD_CONTRACT.items():
        lines.append(f"| {metric} | {rule['op']} | {rule['value']} |")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_target_templates(results: List[Dict[str, object]]) -> Dict[str, Dict[str, Any]]:
    all_suites_ok = all(bool(row.get("ok")) for row in results) and len(results) > 0
    templates: Dict[str, Dict[str, Any]] = {}
    for target_id, protocol in TARGET_PROTOCOLS.items():
        requires_field = len(protocol["manual_dependencies"]) > 0
        templates[target_id] = {
            "title": protocol["title"],
            "objective": protocol["objective"],
            "acceptance_criteria": list(protocol["acceptance_criteria"]),
            "manual_dependencies": list(protocol["manual_dependencies"]),
            "local_tooling_ready": all_suites_ok,
            "evidence_state": "pending-field" if requires_field else ("ready-local" if all_suites_ok else "blocked-local"),
            "execution_template": {
                "artifact_paths": [
                    *ARTIFACT_STRUCTURE_REQUIRED_FILES,
                ],
                "required_notes": [
                    "scenario_id",
                    "scenario",
                    "symptom",
                    "timestamps",
                    "observed_state_transitions",
                    "suspected_root_cause",
                    "observed_signal",
                    "next_action",
                    "evidence_ref",
                    "resultado",
                ],
            },
        }
        if target_id == "OVR-STAB-QA-04":
            templates[target_id]["execution_template"]["monitor_dpi_matrix"] = list(CEN04_MONITOR_DPI_MATRIX)
            templates[target_id]["execution_template"]["reproduction_steps"] = list(CEN04_REPRO_STEPS)
            templates[target_id]["execution_template"]["drift_collection_required_fields"] = list(
                DRIFT_COLLECTION_REQUIRED_FIELDS
            )
        if target_id == "OVR-STAB-QA-03":
            templates[target_id]["execution_template"]["injection_protocol_steps"] = list(CEN03_INJECTION_PROTOCOL_STEPS)
            templates[target_id]["execution_template"]["operator_direct_flow"] = list(CEN03_OPERATOR_DIRECT_FLOW)
            templates[target_id]["execution_template"]["required_signals"] = dict(CEN03_REQUIRED_SIGNALS)
            templates[target_id]["execution_template"]["required_transitions"] = list(CEN03_REQUIRED_TRANSITIONS)
            templates[target_id]["execution_template"]["incident_minimum_evidence"] = dict(CEN03_INCIDENT_MIN_EVIDENCE)
            templates[target_id]["execution_template"]["evidence_template_required_fields"] = list(
                CEN03_EVIDENCE_TEMPLATE_REQUIRED_FIELDS
            )
            templates[target_id]["execution_template"]["incident_examples"] = list(CEN03_INCIDENT_EXAMPLES)
        if target_id == "OVR-STAB-AUD-05":
            templates[target_id]["execution_template"]["cen02_execution_steps"] = list(CEN02_EXECUTION_STEPS)
            templates[target_id]["execution_template"]["cen02_required_transitions"] = list(CEN02_REQUIRED_TRANSITIONS)
            templates[target_id]["execution_template"]["cen02_transition_required_fields"] = list(
                CEN02_TRANSITION_REQUIRED_FIELDS
            )
            templates[target_id]["execution_template"]["cen02_step_required_fields"] = list(CEN02_STEP_REQUIRED_FIELDS)
            templates[target_id]["execution_template"]["cen02_quality_gates"] = dict(CEN02_QUALITY_GATES)
    return templates


def get_git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            check=False,
            shell=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return (proc.stdout or "").strip() or "unknown"


def summarize_suite_failures(results: List[Dict[str, object]], out_dir: Path) -> List[Dict[str, str]]:
    failures: List[Dict[str, str]] = []
    for row in results:
        if bool(row.get("ok")):
            continue
        suite_id = str(row.get("id", "unknown"))
        stderr_log = out_dir / f"{suite_id}.stderr.log"
        stderr_tail_hint = ""
        failure_reason = "suite-exit-nonzero"
        if stderr_log.exists():
            lines = stderr_log.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(lines):
                clean = line.strip()
                if clean:
                    stderr_tail_hint = clean[:240]
                    break
        if "AssertionError" in stderr_tail_hint:
            failure_reason = "assertion-failure"
        elif "ImportError" in stderr_tail_hint or "ModuleNotFoundError" in stderr_tail_hint:
            failure_reason = "import-failure"
        failures.append(
            {
                "suite_id": suite_id,
                "failure_reason": failure_reason,
                "stderr_tail_hint": stderr_tail_hint,
            }
        )
    return failures


def build_ovr_blockers(results: List[Dict[str, object]]) -> Dict[str, List[str]]:
    blockers: Dict[str, List[str]] = {}
    for ovr_id in OVR_TARGETS:
        blocker_suites = [
            str(row["id"])
            for row in results
            if ovr_id in row["ovr"] and not bool(row["ok"])  # type: ignore[operator]
        ]
        blockers[ovr_id] = blocker_suites
    return blockers


def build_evidence_integrity_report(
    results: List[Dict[str, object]], out_dir: Path, include_summary_manifest: bool = False
) -> Dict[str, object]:
    required_files = ARTIFACT_STRUCTURE_REQUIRED_FILES_FINAL if include_summary_manifest else ARTIFACT_STRUCTURE_REQUIRED_FILES
    expected_files = [out_dir / rel_path for rel_path in required_files]
    missing_or_empty = [str(path) for path in expected_files if not path.exists() or path.stat().st_size <= 0]
    suite_logs_ok = True
    missing_logs: List[str] = []
    for row in results:
        for suffix in ("stdout.log", "stderr.log"):
            log_path = out_dir / f"{row['id']}.{suffix}"
            if not log_path.exists():
                suite_logs_ok = False
                missing_logs.append(str(log_path))
    summary_csv_rows = 0
    summary_csv_path = out_dir / "summary.csv"
    if summary_csv_path.exists():
        with summary_csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            summary_csv_rows = max(0, sum(1 for _ in reader) - 1)
    row_count_match = summary_csv_rows == len(results)
    ok = not missing_or_empty and suite_logs_ok and row_count_match
    return {
        "ok": ok,
        "missing_or_empty_artifacts": missing_or_empty,
        "missing_suite_logs": missing_logs,
        "summary_csv_rows": summary_csv_rows,
        "results_rows": len(results),
        "row_count_match": row_count_match,
    }


def validate_target_protocols(templates: Dict[str, Dict[str, Any]]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    obs_09 = templates.get("OVR-STAB-OBS-09", {})
    required_notes = set(obs_09.get("execution_template", {}).get("required_notes", []))
    for field in (
        "scenario_id",
        "symptom",
        "observed_state_transitions",
        "suspected_root_cause",
        "observed_signal",
        "next_action",
        "evidence_ref",
    ):
        if field not in required_notes:
            errors.append(f"OVR-STAB-OBS-09 missing required note: {field}")
    qa_04 = templates.get("OVR-STAB-QA-04", {})
    qa_04_execution = qa_04.get("execution_template", {})
    qa_04_matrix = qa_04_execution.get("monitor_dpi_matrix", [])
    if not isinstance(qa_04_matrix, list) or not qa_04_matrix:
        errors.append("OVR-STAB-QA-04 monitor_dpi_matrix missing/invalid")
        qa_04_matrix = []
    seen_monitor_ids: set[str] = set()
    for index, item in enumerate(qa_04_matrix):
        if not isinstance(item, dict):
            errors.append(f"OVR-STAB-QA-04 monitor_dpi_matrix row {index} is not an object")
            continue
        for field in REQUIRED_CEN04_MONITOR_FIELDS:
            if field not in item:
                errors.append(f"OVR-STAB-QA-04 monitor_dpi_matrix row {index} missing field: {field}")
        monitor_id = str(item.get("monitor_id", "")).strip()
        if not monitor_id:
            errors.append(f"OVR-STAB-QA-04 monitor_dpi_matrix row {index} monitor_id empty")
        elif monitor_id in seen_monitor_ids:
            errors.append(f"OVR-STAB-QA-04 monitor_dpi_matrix duplicated monitor_id: {monitor_id}")
        else:
            seen_monitor_ids.add(monitor_id)
        try:
            dpi_percent = int(item.get("dpi_percent", 0))
            if dpi_percent <= 0:
                errors.append(f"OVR-STAB-QA-04 monitor_dpi_matrix row {index} invalid dpi_percent: {dpi_percent}")
        except (TypeError, ValueError):
            errors.append(f"OVR-STAB-QA-04 monitor_dpi_matrix row {index} dpi_percent is not integer")
        transition = str(item.get("transition", "")).strip()
        if transition not in CEN04_ALLOWED_TRANSITIONS:
            errors.append(
                "OVR-STAB-QA-04 monitor_dpi_matrix row "
                f"{index} invalid transition: {transition or '<empty>'}"
            )
    qa_04_dpi_values = set()
    for item in qa_04_matrix:
        if not isinstance(item, dict):
            continue
        try:
            qa_04_dpi_values.add(int(item.get("dpi_percent", 0)))
        except (TypeError, ValueError):
            continue
    qa_04_dpi = sorted(qa_04_dpi_values)
    if qa_04_dpi != [100, 125, 150]:
        errors.append("OVR-STAB-QA-04 invalid monitor_dpi_matrix (required DPI: 100/125/150)")
    qa_04_steps = set(qa_04_execution.get("reproduction_steps", []))
    for step in CEN04_REPRO_STEPS:
        if step not in qa_04_steps:
            errors.append(f"OVR-STAB-QA-04 missing reproduction step: {step}")
    qa_04_drift_fields = set(qa_04_execution.get("drift_collection_required_fields", []))
    for field in DRIFT_COLLECTION_REQUIRED_FIELDS:
        if field not in qa_04_drift_fields:
            errors.append(f"OVR-STAB-QA-04 missing drift field: {field}")
    qa_03 = templates.get("OVR-STAB-QA-03", {})
    qa_03_execution = qa_03.get("execution_template", {})
    qa_03_steps = set(qa_03_execution.get("injection_protocol_steps", []))
    for step in CEN03_INJECTION_PROTOCOL_STEPS:
        if step not in qa_03_steps:
            errors.append(f"OVR-STAB-QA-03 missing injection protocol step: {step}")
    qa_03_signals = qa_03_execution.get("required_signals", {})
    for channel, fields in CEN03_REQUIRED_SIGNALS.items():
        channel_fields = set(qa_03_signals.get(channel, [])) if isinstance(qa_03_signals, dict) else set()
        for field in fields:
            if field not in channel_fields:
                errors.append(f"OVR-STAB-QA-03 missing {channel} signal: {field}")
    qa_03_template_fields = set(qa_03_execution.get("evidence_template_required_fields", []))
    for field in CEN03_EVIDENCE_TEMPLATE_REQUIRED_FIELDS:
        if field not in qa_03_template_fields:
            errors.append(f"OVR-STAB-QA-03 missing evidence template field: {field}")
    qa_03_required_transitions = set(qa_03_execution.get("required_transitions", []))
    for transition in CEN03_REQUIRED_TRANSITIONS:
        if transition not in qa_03_required_transitions:
            errors.append(f"OVR-STAB-QA-03 missing required transition: {transition}")
    qa_03_incident_min_evidence = qa_03_execution.get("incident_minimum_evidence", {})
    if not isinstance(qa_03_incident_min_evidence, dict):
        errors.append("OVR-STAB-QA-03 incident_minimum_evidence must be object")
        qa_03_incident_min_evidence = {}
    min_refs = int(qa_03_incident_min_evidence.get("min_evidence_refs", 0) or 0)
    if min_refs < int(CEN03_INCIDENT_MIN_EVIDENCE["min_evidence_refs"]):
        errors.append(
            f"OVR-STAB-QA-03 min_evidence_refs<{CEN03_INCIDENT_MIN_EVIDENCE['min_evidence_refs']}: {min_refs}"
        )
    incident_artifact_kinds = set(qa_03_incident_min_evidence.get("required_artifact_kinds", []))
    for artifact_kind in CEN03_INCIDENT_MIN_EVIDENCE["required_artifact_kinds"]:
        if artifact_kind not in incident_artifact_kinds:
            errors.append(f"OVR-STAB-QA-03 missing incident artifact kind: {artifact_kind}")
    incident_channels = set(qa_03_incident_min_evidence.get("required_channels_with_expected_vs_observed", []))
    for channel in CEN03_INCIDENT_MIN_EVIDENCE["required_channels_with_expected_vs_observed"]:
        if channel not in incident_channels:
            errors.append(f"OVR-STAB-QA-03 missing incident channel comparison: {channel}")
    incident_fields = set(qa_03_incident_min_evidence.get("required_incident_fields", []))
    for field in CEN03_INCIDENT_MIN_EVIDENCE["required_incident_fields"]:
        if field not in incident_fields:
            errors.append(f"OVR-STAB-QA-03 missing incident required field: {field}")
    operator_flow_rows = qa_03_execution.get("operator_direct_flow", [])
    if not isinstance(operator_flow_rows, list) or not operator_flow_rows:
        errors.append("OVR-STAB-QA-03 operator_direct_flow missing/invalid")
    else:
        for idx, row in enumerate(operator_flow_rows):
            if not isinstance(row, dict):
                errors.append(f"OVR-STAB-QA-03 operator_direct_flow row {idx} is not object")
                continue
            for field in ("step_id", "operator_action", "expected_result", "evidence_required"):
                if not str(row.get(field, "")).strip():
                    errors.append(f"OVR-STAB-QA-03 operator_direct_flow row {idx} missing field: {field}")
    incident_examples = qa_03_execution.get("incident_examples", [])
    if not isinstance(incident_examples, list) or not incident_examples:
        errors.append("OVR-STAB-QA-03 incident_examples missing/invalid")
    else:
        for idx, item in enumerate(incident_examples):
            if not isinstance(item, dict):
                errors.append(f"OVR-STAB-QA-03 incident_examples row {idx} is not object")
                continue
            for field in ("incident_id", "scenario_id", "symptom", "suspected_root_cause", "action_taken", "result"):
                if not str(item.get(field, "")).strip():
                    errors.append(f"OVR-STAB-QA-03 incident_examples row {idx} missing field: {field}")
            refs = item.get("evidence_ref", [])
            if not isinstance(refs, list) or len(refs) < int(CEN03_INCIDENT_MIN_EVIDENCE["min_evidence_refs"]):
                errors.append(f"OVR-STAB-QA-03 incident_examples row {idx} requires >=3 evidence_ref entries")
    aud_05 = templates.get("OVR-STAB-AUD-05", {})
    aud_05_execution = aud_05.get("execution_template", {})
    cen02_steps = set(aud_05_execution.get("cen02_execution_steps", []))
    for step in CEN02_EXECUTION_STEPS:
        if step not in cen02_steps:
            errors.append(f"OVR-STAB-AUD-05 missing CEN-02 execution step: {step}")
    cen02_transitions = set(aud_05_execution.get("cen02_required_transitions", []))
    for transition in CEN02_REQUIRED_TRANSITIONS:
        if transition not in cen02_transitions:
            errors.append(f"OVR-STAB-AUD-05 missing CEN-02 required transition: {transition}")
    cen02_transition_fields = set(aud_05_execution.get("cen02_transition_required_fields", []))
    for field in CEN02_TRANSITION_REQUIRED_FIELDS:
        if field not in cen02_transition_fields:
            errors.append(f"OVR-STAB-AUD-05 missing CEN-02 transition field: {field}")
    cen02_step_fields = set(aud_05_execution.get("cen02_step_required_fields", []))
    for field in CEN02_STEP_REQUIRED_FIELDS:
        if field not in cen02_step_fields:
            errors.append(f"OVR-STAB-AUD-05 missing CEN-02 step field: {field}")
    cen02_quality_gates = aud_05_execution.get("cen02_quality_gates", {})
    if not isinstance(cen02_quality_gates, dict):
        errors.append("OVR-STAB-AUD-05 CEN-02 quality gates must be object")
        cen02_quality_gates = {}
    for metric, rule in CEN02_QUALITY_GATES.items():
        gate = cen02_quality_gates.get(metric)
        if not isinstance(gate, dict):
            errors.append(f"OVR-STAB-AUD-05 missing CEN-02 quality gate: {metric}")
            continue
        if gate.get("op") != rule["op"] or float(gate.get("value", -9999.0)) != float(rule["value"]):
            errors.append(f"OVR-STAB-AUD-05 invalid CEN-02 quality gate: {metric}")
    return (len(errors) == 0, errors)


def enforce_required_ovr(ovr_status: Dict[str, Dict[str, object]], required_ovrs: List[str], mode: str) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    for ovr_id in required_ovrs:
        entry = ovr_status.get(ovr_id)
        if entry is None:
            errors.append(f"required OVR not present: {ovr_id}")
            continue
        state = str(entry.get("state", "unknown"))
        if mode == "local" and ovr_id == "OVR-STAB-QA-04":
            if state not in {"not-covered", "partial-done"}:
                errors.append(f"{ovr_id} invalid state for local mode: {state}")
            continue
        if state != "partial-done":
            errors.append(f"{ovr_id} not partial-done (state={state})")
    return (len(errors) == 0, errors)


def validate_trace_completeness_contract() -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from distributor.ocr_overlay_audit import OcrOverlayAuditTrail, build_frame_record, build_session_metadata

    session_meta = build_session_metadata(session_id="trace-contract-session", symbol="WINJ26", refresh_ms=500)
    frame_row = build_frame_record(
        session_id="trace-contract-session",
        seq=1,
        status="STABLE",
        labels=[{"value": 123.0, "y_screen": 100.0}],
        axis_fit={"slope": -0.2, "intercept": 180000.0, "residual_px": 1.0, "confidence": 0.8},
        axis={"slope": -0.2, "intercept": 180000.0},
        lines=[{"label": "POC", "value": 123.0, "y_screen": 100.0, "status": "visible"}],
    )
    for field in TRACE_REQUIRED_SESSION_FIELDS:
        if field not in session_meta:
            errors.append(f"trace session missing field: {field}")
    for field in TRACE_REQUIRED_FRAME_FIELDS:
        if field not in frame_row:
            errors.append(f"trace frame missing field: {field}")
    render_indicators = frame_row.get("render_indicators", {})
    if not isinstance(render_indicators, dict):
        errors.append("trace frame render_indicators must be object")
        render_indicators = {}
    for field in TRACE_REQUIRED_RENDER_INDICATOR_FIELDS:
        if field not in render_indicators:
            errors.append(f"trace render_indicators missing field: {field}")

    trail = OcrOverlayAuditTrail(
        trace_path=str(ROOT / "distributor" / "logs" / ".tmp_trace_contract.jsonl"),
        session_metadata=session_meta,
    )
    row_a = trail._normalize_record({"event": "frame", "status": "STABLE", "seq": 1})  # pylint: disable=protected-access
    row_b = trail._normalize_record(  # pylint: disable=protected-access
        {"event": "frame", "status": "FROZEN", "seq": 2, "status_transition": {"to": "FROZEN"}}
    )
    status_transition = row_b.get("status_transition", {})
    if not isinstance(status_transition, dict):
        errors.append("trace status_transition must be object")
        status_transition = {}
    for field in TRACE_REQUIRED_STATUS_TRANSITION_FIELDS:
        if field not in status_transition:
            errors.append(f"trace status_transition missing field: {field}")
    if status_transition.get("from") != "STABLE" or status_transition.get("to") != "FROZEN":
        errors.append("trace status_transition does not preserve status sequence")
    first_transition = row_a.get("status_transition", {})
    if isinstance(first_transition, dict) and bool(first_transition.get("changed")):
        errors.append("trace first status_transition.changed must be false")
    return (len(errors) == 0, errors)


def validate_trace_schema_fixture_contract(
    schema_path: Path = TRACE_SCHEMA_PATH, fixture_path: Path = TRACE_FIXTURE_PATH
) -> Tuple[bool, List[str], Dict[str, Any]]:
    errors: List[str] = []
    report: Dict[str, Any] = {
        "schema_path": str(schema_path),
        "fixture_path": str(fixture_path),
        "rows_checked": 0,
    }
    if not schema_path.exists():
        return (False, [f"trace schema missing: {schema_path}"], report)
    if not fixture_path.exists():
        return (False, [f"trace fixture missing: {fixture_path}"], report)
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive parsing
        return (False, [f"trace schema invalid json: {exc}"], report)
    if not isinstance(schema, dict):
        return (False, ["trace schema root must be object"], report)
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        errors.append("trace schema missing $defs")
    else:
        if "session_start_event" not in defs:
            errors.append("trace schema missing $defs.session_start_event")
        if "frame_event" not in defs:
            errors.append("trace schema missing $defs.frame_event")
    one_of = schema.get("oneOf")
    if not isinstance(one_of, list) or len(one_of) < 2:
        errors.append("trace schema oneOf must declare session_start and frame variants")

    lines = fixture_path.read_text(encoding="utf-8").splitlines()
    parsed_rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(lines, start=1):
        content = raw.strip()
        if not content:
            continue
        try:
            row = json.loads(content)
        except Exception as exc:
            errors.append(f"trace fixture line {idx} invalid json: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"trace fixture line {idx} must be object")
            continue
        parsed_rows.append(row)
    report["rows_checked"] = len(parsed_rows)
    if not parsed_rows:
        errors.append("trace fixture must contain at least one event row")
        return (False, errors, report)

    session_rows = 0
    frame_rows = 0
    for idx, row in enumerate(parsed_rows, start=1):
        event = str(row.get("event", "")).strip()
        required_fields = TRACE_REQUIRED_BY_EVENT.get(event)
        if required_fields is None:
            errors.append(f"trace fixture line {idx} has unsupported event: {event or '<empty>'}")
            continue
        if event == "session_start":
            session_rows += 1
        if event == "frame":
            frame_rows += 1
        for field in required_fields:
            if field not in row:
                errors.append(f"trace fixture line {idx} missing field: {field}")
        if event == "frame":
            render = row.get("render_indicators")
            if not isinstance(render, dict):
                errors.append(f"trace fixture line {idx} render_indicators must be object")
            else:
                for field in TRACE_REQUIRED_RENDER_INDICATOR_FIELDS:
                    if field not in render:
                        errors.append(f"trace fixture line {idx} render_indicators missing field: {field}")
            transition = row.get("status_transition")
            if not isinstance(transition, dict):
                errors.append(f"trace fixture line {idx} status_transition must be object")
            else:
                for field in TRACE_REQUIRED_STATUS_TRANSITION_FIELDS:
                    if field not in transition:
                        errors.append(f"trace fixture line {idx} status_transition missing field: {field}")
    if session_rows < 1:
        errors.append("trace fixture must contain at least one session_start event")
    if frame_rows < 1:
        errors.append("trace fixture must contain at least one frame event")
    report["session_rows"] = session_rows
    report["frame_rows"] = frame_rows
    return (len(errors) == 0, errors, report)


def _metric_contract_violations(row: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for metric, rule in CEN05_LOAD_THRESHOLD_CONTRACT.items():
        if metric not in row:
            errors.append(f"missing metric in stress row: {metric}")
            continue
        value = float(row[metric])
        target = float(rule["value"])
        op = str(rule["op"])
        if op == "<=" and value > target:
            errors.append(f"{metric}={value} > {target}")
        elif op == ">=" and value < target:
            errors.append(f"{metric}={value} < {target}")
    return errors


def validate_cen05_stress_manifest(path: Path | None) -> Tuple[bool, List[str], Dict[str, Any]]:
    if path is None:
        return (False, ["cen05_stress_manifest not provided"], {})
    if not path.exists():
        return (False, [f"cen05_stress_manifest missing: {path}"], {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return (False, [f"cen05_stress_manifest invalid json: {exc}"], {})
    errors: List[str] = []
    if not bool(payload.get("overall_ok", False)):
        errors.append("cen05_stress_manifest overall_ok != true")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("cen05_stress_manifest rows missing/empty")
    else:
        for row in rows:
            if not isinstance(row, dict):
                errors.append("cen05_stress_manifest row is not an object")
                continue
            scenario = str(row.get("scenario", "unknown"))
            violations = _metric_contract_violations(row)
            errors.extend(f"{scenario}: {violation}" for violation in violations)
    return (len(errors) == 0, errors, {"path": str(path), "rows_checked": len(rows) if isinstance(rows, list) else 0})


def write_target_protocols_manifest(path: Path, templates: Dict[str, Dict[str, Any]]) -> None:
    payload = {
        "runner": "run_ovr_stab_qa_evidence.py",
        "scope": "target-protocols-ovr-stab-aud-qa-obs",
        "artifact_naming": {
            "pattern": "ovr-stab-<scenario_id>-<artifact_kind>-<utc_compact>.<ext>",
            "allowed_artifact_kinds": ["screenshot", "video", "trace", "log-snippet", "manifest-ref"],
            "utc_compact_example": "20260430T174500Z",
        },
        "targets": templates,
        "cen05_threshold_contract": CEN05_LOAD_THRESHOLD_CONTRACT,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_target_protocols_checklist(path: Path, templates: Dict[str, Dict[str, Any]]) -> None:
    lines: List[str] = [
        "# OVR STAB - Checklist executavel de evidencias",
        "",
        "Uso: preencher este checklist na mesma pasta dos artefatos locais para preparar execucao de campo.",
        "",
    ]
    for target_id in (
        "OVR-STAB-AUD-04",
        "OVR-STAB-AUD-05",
        "OVR-STAB-QA-03",
        "OVR-STAB-QA-04",
        "OVR-STAB-QA-05",
        "OVR-STAB-OBS-09",
    ):
        item = templates[target_id]
        lines.append(f"## {target_id} - {item['title']}")
        lines.append("")
        lines.append(f"- objective: {item['objective']}")
        lines.append(f"- local_tooling_ready: {int(bool(item['local_tooling_ready']))}")
        lines.append(f"- evidence_state: {item['evidence_state']}")
        lines.append("- acceptance_criteria:")
        for criterion in item["acceptance_criteria"]:
            lines.append(f"  - [ ] {criterion}")
        lines.append("- manual_dependencies:")
        if item["manual_dependencies"]:
            for dep in item["manual_dependencies"]:
                lines.append(f"  - [ ] {dep}")
        else:
            lines.append("  - [ ] nenhuma")
        lines.append("- notes:")
        lines.append("  - scenario_id:")
        lines.append("  - scenario:")
        lines.append("  - symptom:")
        lines.append("  - timestamps:")
        lines.append("  - observed_state_transitions:")
        lines.append("  - suspected_root_cause:")
        lines.append("  - observed_signal:")
        lines.append("  - next_action:")
        lines.append("  - evidence_ref:")
        lines.append("  - resultado: pass|fail|blocked")
        lines.append("")
        if target_id == "OVR-STAB-QA-03":
            lines.append("### OVR-STAB-QA-03 - protocolo padronizado de injeção/observação")
            lines.append("")
            lines.append("- injection_protocol_steps:")
            for step_id in CEN03_INJECTION_PROTOCOL_STEPS:
                lines.append(f"  - [ ] {step_id}")
            lines.append("- operator_direct_flow:")
            lines.append("  | step_id | operator_action | expected_result | evidence_required |")
            lines.append("  | --- | --- | --- | --- |")
            for flow in CEN03_OPERATOR_DIRECT_FLOW:
                lines.append(
                    f"  | {flow['step_id']} | {flow['operator_action']} | {flow['expected_result']} | {flow['evidence_required']} |"
                )
            lines.append("- expected_signals_by_channel:")
            for channel, fields in CEN03_REQUIRED_SIGNALS.items():
                lines.append(f"  - {channel}:")
                for field in fields:
                    lines.append(f"    - [ ] {field}")
            lines.append("- required_transitions:")
            for transition in CEN03_REQUIRED_TRANSITIONS:
                lines.append(f"  - [ ] {transition}")
            lines.append("- incident_minimum_evidence:")
            lines.append(f"  - min_evidence_refs: {CEN03_INCIDENT_MIN_EVIDENCE['min_evidence_refs']}")
            lines.append("  - required_artifact_kinds:")
            for artifact_kind in CEN03_INCIDENT_MIN_EVIDENCE["required_artifact_kinds"]:
                lines.append(f"    - [ ] {artifact_kind}")
            lines.append("  - required_channels_with_expected_vs_observed:")
            for channel in CEN03_INCIDENT_MIN_EVIDENCE["required_channels_with_expected_vs_observed"]:
                lines.append(f"    - [ ] {channel}")
            lines.append("- evidence_template_required_fields:")
            for field in CEN03_EVIDENCE_TEMPLATE_REQUIRED_FIELDS:
                lines.append(f"  - [ ] {field}")
            lines.append("")
            lines.append("#### CEN-03 - incidentes minimos por evidencia")
            lines.append("")
            lines.append(
                "| incident_id | transition_observed | expected_vs_observed_hud | expected_vs_observed_status_endpoint | expected_vs_observed_trace_jsonl | evidence_ref_1 | evidence_ref_2 | evidence_ref_3 | resultado |"
            )
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            lines.append("| CEN-03-INC-001 | [ ] | [ ] | [ ] | [ ] |  |  |  | pass|fail|blocked |")
            lines.append("")
            lines.append("#### CEN-03 - exemplos prontos de incidente")
            lines.append("")
            lines.append("| incident_id | symptom | suspected_root_cause | action_taken | result | evidence_ref_example |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for item in CEN03_INCIDENT_EXAMPLES:
                evidence_sample = ", ".join(item["evidence_ref"])  # type: ignore[index]
                lines.append(
                    f"| {item['incident_id']} | {item['symptom']} | {item['suspected_root_cause']} | "
                    f"{item['action_taken']} | {item['result']} | {evidence_sample} |"
                )
            lines.append("")

    lines.append("## OVR-STAB-QA-04 - matriz DPI")
    lines.append("")
    lines.append("| monitor_id | dpi_percent | step_id | transition | bounds_ok | overlay_ok | drift_px | drift_band | evidence_ref |")
    lines.append("| --- | ---: | --- | --- | --- | --- | ---: | --- | --- |")
    for row in CEN04_MONITOR_DPI_MATRIX:
        lines.append(
            f"| {row['monitor_id']} | {row['dpi_percent']} | open_window_on_baseline_monitor | {row['transition']} | [ ] | [ ] |  | <=3.0px |  |"
        )
    lines.append("")
    lines.append("## OVR-STAB-QA-04 - passos de reproducao")
    lines.append("")
    lines.append("| step_id | executed | timestamp_utc | monitor_id | dpi_percent | axis_status_before | axis_status_after | drift_px | evidence_ref |")
    lines.append("| --- | --- | --- | --- | ---: | --- | --- | ---: | --- |")
    for step_id in CEN04_REPRO_STEPS:
        lines.append(f"| {step_id} | [ ] |  |  |  |  |  |  |  |")
    lines.append("")
    lines.append("## OVR-STAB-QA-04 - coleta padronizada de drift")
    lines.append("")
    lines.append("Campos obrigatorios por medicao:")
    for field in DRIFT_COLLECTION_REQUIRED_FIELDS:
        lines.append(f"- {field}")
    lines.append("")
    lines.append("## CEN-05 (carga) - contrato objetivo de thresholds")
    lines.append("")
    lines.append("| metric | operator | threshold |")
    lines.append("| --- | --- | ---: |")
    for metric, rule in CEN05_LOAD_THRESHOLD_CONTRACT.items():
        lines.append(f"| {metric} | {rule['op']} | {rule['value']} |")
    lines.append("")
    lines.append("### CEN-05 - execucao operacional imediata")
    lines.append("")
    lines.append("| step_id | executed | timestamp_utc | observed_value | threshold_contract | evidence_ref |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append("| run_overlay_ws_stress_regression_strict | [ ] |  |  | all_metrics_contract |  |")
    lines.append("| attach_stress_artifacts_bundle | [ ] |  |  | stress.csv+summary.md+summary.manifest.json |  |")
    lines.append("| verify_market_session_context | [ ] |  |  | market_open_or_representative_replay |  |")
    lines.append("| confirm_no_backlog_growth | [ ] |  |  | backlog_growth_ratio<=1.5 |  |")
    lines.append("| confirm_publish_band_and_fps | [ ] |  |  | floor/overshoot/fps/jitter/latency |  |")
    lines.append("")
    lines.append("### CEN-05 - criterios mensuraveis de aceite")
    lines.append("")
    lines.append("- [ ] `queue_max<=1` em todos os cenarios")
    lines.append("- [ ] `backlog_growth_ratio<=1.5` em todos os cenarios")
    lines.append("- [ ] `latency_p95_ms<=60` e `latency_p99_ms<=120` em todos os cenarios")
    lines.append("- [ ] `consumer_fps>=90`, `publish_rate_floor_ratio>=0.75`, `publish_rate_overshoot_ratio<=1.15`")
    lines.append("- [ ] `publish_interval_jitter_cv<=0.35` e `summary.manifest.json overall_ok=1`")
    lines.append("")
    lines.append("## CEN-02 (zoom/escala) - roteiro operacional objetivo")
    lines.append("")
    lines.append("- target_ids: OVR-STAB-AUD-05, OVR-STAB-QA-02")
    lines.append("- objetivo: comprovar transicoes SUSPECT/FROZEN/RECALIBRATING com estabilizacao final.")
    lines.append("- criterio_gate: so concluir quando todas as transicoes obrigatorias tiverem evidencia.")
    lines.append("- comandos_executaveis:")
    lines.append("  - `python scripts/run_ovr_stab_qa_evidence.py --strict --mode field-ready --require-ovr OVR-STAB-QA-02 --require-ovr OVR-STAB-OBS-09`")
    lines.append("  - `python scripts/verify_ovr_stab_g8_readiness.py --qa-manifest \"<out-dir>/summary.manifest.json\"`")
    lines.append("- pre-check imediato:")
    lines.append("  - [ ] summary.manifest.json presente e nao vazio")
    lines.append("  - [ ] feed/replay ativo e overlay com axis_status visivel")
    lines.append("  - [ ] trace/screenshot/video habilitados antes do primeiro evento")
    lines.append("")
    lines.append("### CEN-02 - passos operacionais")
    lines.append("")
    lines.append("| step_id | executed | timestamp_utc | action | axis_status_before | axis_status_after | stable_reached | evidence_ref |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for step_id in CEN02_EXECUTION_STEPS:
        lines.append(f"| {step_id} | [ ] |  |  |  |  | [ ] |  |")
    lines.append("")
    lines.append("### CEN-02 - captura de transicoes obrigatorias")
    lines.append("")
    lines.append("| transition_state | observed | event_timestamp_utc | pre_window_ref | post_window_ref | trigger_action | drift_px_peak | evidence_ref |")
    lines.append("| --- | --- | --- | --- | --- | --- | ---: | --- |")
    for transition in CEN02_REQUIRED_TRANSITIONS:
        lines.append(f"| {transition} | [ ] |  |  |  |  |  |  |")
    lines.append("")
    lines.append("### CEN-02 - evidencia minima por transicao")
    lines.append("")
    lines.append("| transition_state | screenshot_ref | trace_ref | status_endpoint_ref | expected_vs_observed | resultado |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for transition in CEN02_REQUIRED_TRANSITIONS:
        lines.append(f"| {transition} |  |  |  |  | pass|fail|blocked |")
    lines.append("")
    lines.append("### CEN-02 - criterios objetivos de aceite")
    lines.append("")
    lines.append("- [ ] transicoes obrigatorias observadas: SUSPECT, FROZEN e RECALIBRATING")
    lines.append("- [ ] retorno para STABLE apos evento de zoom/escala registrado")
    lines.append("- [ ] sem oscilacao persistente apos estabilizacao (drift_px_max <= 3.0)")
    lines.append("- [ ] cada transicao possui evidence_ref rastreavel")
    lines.append("")
    lines.append("### CEN-02 - contrato de qualidade automatizado")
    lines.append("")
    lines.append("| metric | operator | threshold | evidence_observed | pass |")
    lines.append("| --- | --- | ---: | --- | --- |")
    for metric, rule in CEN02_QUALITY_GATES.items():
        lines.append(f"| {metric} | {rule['op']} | {rule['value']} |  | [ ] |")
    lines.append("")
    lines.append("### CEN-02 - registro rapido de bloqueio")
    lines.append("")
    lines.append("- blocked_reason:")
    lines.append("- owner:")
    lines.append("- eta:")
    lines.append("- next_action:")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (ROOT / "distributor" / "logs" / f"ovr-stab-qa-evidence-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    results: List[Dict[str, object]] = []
    for suite in DEFAULT_SUITES:
        result = run_suite(suite, out_dir)
        results.append(result)
        if args.stop_on_fail and not bool(result["ok"]):
            break

    overall_ok = all(bool(item["ok"]) for item in results)
    ovr_status = build_ovr_status(results)

    summary_csv = out_dir / "summary.csv"
    summary_md = out_dir / "summary.md"
    summary_manifest = out_dir / "summary.manifest.json"
    target_protocols_manifest = out_dir / "target_protocols.manifest.json"
    target_protocols_checklist = out_dir / "target_protocols.checklist.md"
    write_summary_csv(summary_csv, results)
    write_summary_md(summary_md, results, ovr_status, overall_ok)
    target_templates = build_target_templates(results)
    write_target_protocols_manifest(target_protocols_manifest, target_templates)
    write_target_protocols_checklist(target_protocols_checklist, target_templates)
    integrity_report = build_evidence_integrity_report(results, out_dir, include_summary_manifest=False)
    target_templates_ok, target_templates_errors = validate_target_protocols(target_templates)
    trace_contract_ok, trace_contract_errors = validate_trace_completeness_contract()
    trace_schema_fixture_ok, trace_schema_fixture_errors, trace_schema_fixture_report = (
        validate_trace_schema_fixture_contract()
    )
    suite_failures = summarize_suite_failures(results, out_dir)
    ovr_blockers = build_ovr_blockers(results)

    required_ovrs = [str(item) for item in args.require_ovr] if args.require_ovr else list(OVR_TARGETS)
    required_ok, required_errors = enforce_required_ovr(ovr_status, required_ovrs, args.mode)
    cen05_manifest_ok = True
    cen05_manifest_errors: List[str] = []
    cen05_manifest_report: Dict[str, Any] = {}
    if "OVR-STAB-QA-05" in required_ovrs:
        cen05_manifest_ok, cen05_manifest_errors, cen05_manifest_report = validate_cen05_stress_manifest(
            args.cen05_stress_manifest
        )
    strict_ok = (
        bool(overall_ok)
        and bool(integrity_report["ok"])
        and target_templates_ok
        and trace_contract_ok
        and trace_schema_fixture_ok
        and required_ok
        and cen05_manifest_ok
    )

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": f"ovr-stab-qa-evidence-{stamp}",
        "git_commit": get_git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "mode": args.mode,
        "cwd": str(ROOT),
        "username": os.environ.get("USERNAME", "unknown"),
        "started_at_epoch_s": started,
        "finished_at_epoch_s": time.time(),
        "overall_ok": overall_ok,
        "strict_ok": strict_ok,
        "runner": "run_ovr_stab_qa_evidence.py",
        "scope": "local-tests-no-profit-session",
        "results": results,
        "ovr_status": ovr_status,
        "ovr_scenario_map": SCENARIO_BY_OVR,
        "required_ovrs": required_ovrs,
        "required_ovrs_ok": required_ok,
        "required_ovrs_errors": required_errors,
        "cen05_stress_manifest_ok": cen05_manifest_ok,
        "cen05_stress_manifest_errors": cen05_manifest_errors,
        "cen05_stress_manifest_report": cen05_manifest_report,
        "integrity_report": integrity_report,
        "suite_failures": suite_failures,
        "ovr_blockers": ovr_blockers,
        "target_protocols_validation_ok": target_templates_ok,
        "target_protocols_validation_errors": target_templates_errors,
        "trace_completeness_validation_ok": trace_contract_ok,
        "trace_completeness_validation_errors": trace_contract_errors,
        "trace_schema_fixture_validation_ok": trace_schema_fixture_ok,
        "trace_schema_fixture_validation_errors": trace_schema_fixture_errors,
        "trace_schema_fixture_validation_report": trace_schema_fixture_report,
        "target_protocols": target_templates,
        "artifacts": {
            "summary_csv": str(summary_csv),
            "summary_md": str(summary_md),
            "summary_manifest": str(summary_manifest),
            "target_protocols_manifest": str(target_protocols_manifest),
            "target_protocols_checklist": str(target_protocols_checklist),
        },
    }
    summary_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["artifact_structure_report_final"] = build_evidence_integrity_report(
        results, out_dir, include_summary_manifest=True
    )
    summary_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    print(f"Wrote: {target_protocols_manifest}")
    print(f"Wrote: {target_protocols_checklist}")
    if args.strict and not strict_ok:
        raise SystemExit(2)
    if not overall_ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
