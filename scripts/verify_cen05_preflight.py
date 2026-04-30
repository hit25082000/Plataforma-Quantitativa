#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"

REQUIRED_STRESS_FILES = ("stress.csv", "summary.md", "summary.manifest.json")
REQUIRED_COMMAND_SNIPPETS = (
    "run_overlay_ws_stress_regression.py",
    "run_ovr_stab_qa_evidence.py",
    "verify_ovr_stab_g8_readiness.py",
)
REQUIRED_ENV_KEYS = ("PROFIT_DLL_USER", "PROFIT_DLL_PASSWORD", "PQ_PROFIT_DLL_PATH")
REQUIRED_OPENING_PATH_KEYS = ("PQ_PROFIT_DLL_PATH",)
REQUIRED_OPENING_SCRIPT_PATHS = (
    ROOT / "scripts" / "run_overlay_ws_stress_regression.py",
    ROOT / "scripts" / "run_ovr_stab_field_bundle.py",
    ROOT / "scripts" / "verify_ovr_stab_g8_readiness.py",
)
REQUIRED_RUNTIME_DEPENDENCIES = (
    ("python", "python", "Executavel Python 3"),
    ("powershell", "powershell", "PowerShell para operacao assistida"),
    ("pytest", "python_module", "pytest para suite focada local"),
)
PREOPEN_MAX_AGE_SECONDS = 6 * 60 * 60
PREOPEN_STATUS_GO = "PREOPEN_GO"
PREOPEN_STATUS_BLOCKED = "PREOPEN_BLOCKED"
PREOPEN_CHECK_CODE_OK = "OK"
PREOPEN_CONTRACT_VERSION = "1.1"

CHECK_REMEDIATION_COMMANDS: Dict[str, str] = {
    "artifacts": "python scripts/run_overlay_ws_stress_regression.py",
    "thresholds": "python scripts/run_overlay_ws_stress_regression.py",
    "commands": "python scripts/run_ovr_stab_field_bundle.py --strict",
    "bundle": "python scripts/run_ovr_stab_field_bundle.py --strict",
    "readiness": "python scripts/verify_ovr_stab_g8_readiness.py --strict",
    "env_doctor": "set PROFIT_DLL_USER=... && set PROFIT_DLL_PASSWORD=... && set PQ_PROFIT_DLL_PATH=... && python scripts/verify_cen05_preflight.py --strict",
    "freshness": "python scripts/run_overlay_ws_stress_regression.py && python scripts/run_ovr_stab_field_bundle.py --strict && python scripts/verify_ovr_stab_g8_readiness.py --strict",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validador preflight CEN-05 para sessao real pre-abertura.")
    parser.add_argument("--stress-manifest", type=Path, default=None)
    parser.add_argument("--commands-file", type=Path, default=None)
    parser.add_argument("--bundle-manifest", type=Path, default=None)
    parser.add_argument("--readiness-manifest", type=Path, default=None)
    parser.add_argument("--max-age-seconds", type=int, default=PREOPEN_MAX_AGE_SECONDS)
    parser.add_argument("--strict", action="store_true", default=False)
    parser.add_argument("--out-dir", type=Path, default=None)
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


def _resolve_commands_file(explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit.resolve()
    latest_bundle = _latest_manifest("ovr-stab-field-bundle-*/summary.manifest.json")
    if latest_bundle is None:
        return None
    candidate = latest_bundle.parent / "commands.ready.md"
    return candidate.resolve() if candidate.exists() else None


def _resolve_stress_manifest(explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit.resolve()
    return _latest_manifest("overlay-ws-stress-regression-*/summary.manifest.json")


def _resolve_bundle_manifest(explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit.resolve()
    return _latest_manifest("ovr-stab-field-bundle-*/summary.manifest.json")


def _resolve_readiness_manifest(explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit.resolve()
    return _latest_manifest("ovr-stab-g8-readiness-*/summary.manifest.json")


def _check_artifacts(stress_manifest_path: Optional[Path]) -> Dict[str, Any]:
    if stress_manifest_path is None or not stress_manifest_path.exists():
        return {
            "check_id": "artifacts",
            "status": "FAIL",
            "preopen_status_code": "ARTIFACTS_MANIFEST_MISSING",
            "details": "stress manifest ausente",
            "missing": ["summary.manifest.json"],
            "next_step": "gerar stress CEN-05: python scripts/run_overlay_ws_stress_regression.py",
        }
    base_dir = stress_manifest_path.parent
    missing = [name for name in REQUIRED_STRESS_FILES if not (base_dir / name).exists()]
    if missing:
        return {
            "check_id": "artifacts",
            "status": "FAIL",
            "preopen_status_code": "ARTIFACTS_REQUIRED_FILES_MISSING",
            "details": "artefatos obrigatorios ausentes no pacote CEN-05",
            "missing": missing,
            "next_step": "regerar bundle CEN-05 e confirmar stress.csv + summary.*",
        }
    return {
        "check_id": "artifacts",
        "status": "PASS",
        "preopen_status_code": PREOPEN_CHECK_CODE_OK,
        "details": f"artefatos presentes em {base_dir}",
        "missing": [],
        "next_step": "nenhum",
    }


def _check_thresholds(stress_manifest: Dict[str, Any]) -> Dict[str, Any]:
    gate = stress_manifest.get("gate", {}) if isinstance(stress_manifest, dict) else {}
    failures = gate.get("failures", []) if isinstance(gate, dict) else []
    gate_ok = bool(isinstance(gate, dict) and gate.get("ok") is True)
    overall_ok = bool(stress_manifest.get("overall_ok") is True) if isinstance(stress_manifest, dict) else False
    if gate_ok and overall_ok:
        return {
            "check_id": "thresholds",
            "status": "PASS",
            "preopen_status_code": PREOPEN_CHECK_CODE_OK,
            "details": "stress gate aprovado (overall_ok=true e gate.ok=true)",
            "failures": [],
            "next_step": "nenhum",
        }
    failure_list = [str(item) for item in failures] if isinstance(failures, list) else ["gate.failures invalido"]
    if not failure_list:
        failure_list = ["overall_ok=false ou gate.ok=false sem detalhamento de falhas"]
    return {
        "check_id": "thresholds",
        "status": "FAIL",
        "preopen_status_code": "THRESHOLDS_GATE_FAILED",
        "details": "thresholds CEN-05 nao aprovados",
        "failures": failure_list,
        "next_step": "corrigir metricas indicadas em gate.failures e repetir run_overlay_ws_stress_regression.py",
    }


def _check_commands(commands_file: Optional[Path]) -> Dict[str, Any]:
    if commands_file is None or not commands_file.exists():
        return {
            "check_id": "commands",
            "status": "FAIL",
            "preopen_status_code": "COMMANDS_FILE_MISSING",
            "details": "commands.ready.md ausente",
            "missing_snippets": list(REQUIRED_COMMAND_SNIPPETS),
            "next_step": "gerar bundle de campo: python scripts/run_ovr_stab_field_bundle.py --strict",
        }
    content = commands_file.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_COMMAND_SNIPPETS if snippet not in content]
    if missing:
        return {
            "check_id": "commands",
            "status": "FAIL",
            "preopen_status_code": "COMMANDS_SNIPPETS_MISSING",
            "details": f"comandos obrigatorios nao encontrados em {commands_file}",
            "missing_snippets": missing,
            "next_step": "atualizar commands.ready.md para incluir sequencia completa CEN-05",
        }
    return {
        "check_id": "commands",
        "status": "PASS",
        "preopen_status_code": PREOPEN_CHECK_CODE_OK,
        "details": f"commands.ready.md valido ({commands_file})",
        "missing_snippets": [],
        "next_step": "nenhum",
    }


def _check_bundle(bundle_manifest_path: Optional[Path], bundle_manifest: Dict[str, Any]) -> Dict[str, Any]:
    if bundle_manifest_path is None or not bundle_manifest_path.exists():
        return {
            "check_id": "bundle",
            "status": "FAIL",
            "preopen_status_code": "BUNDLE_MANIFEST_MISSING",
            "details": "bundle summary.manifest.json ausente",
            "next_step": "executar: python scripts/run_ovr_stab_field_bundle.py --strict",
        }
    strict_ok = bool(bundle_manifest.get("strict_ok") is True)
    if strict_ok:
        return {
            "check_id": "bundle",
            "status": "PASS",
            "preopen_status_code": PREOPEN_CHECK_CODE_OK,
            "details": f"bundle estrito aprovado ({bundle_manifest_path})",
            "next_step": "nenhum",
        }
    return {
        "check_id": "bundle",
        "status": "FAIL",
        "preopen_status_code": "BUNDLE_STRICT_FAILED",
        "details": f"bundle estrito reprovado ({bundle_manifest_path})",
        "next_step": "corrigir gaps do bundle e repetir run_ovr_stab_field_bundle.py --strict",
    }


def _check_readiness(readiness_manifest_path: Optional[Path], readiness_manifest: Dict[str, Any]) -> Dict[str, Any]:
    if readiness_manifest_path is None or not readiness_manifest_path.exists():
        return {
            "check_id": "readiness",
            "status": "FAIL",
            "preopen_status_code": "READINESS_MANIFEST_MISSING",
            "details": "readiness summary.manifest.json ausente",
            "next_step": "executar: python scripts/verify_ovr_stab_g8_readiness.py --strict",
        }
    g8_ready = bool(readiness_manifest.get("g8_ready") is True)
    scenario_results = readiness_manifest.get("scenario_results", [])
    required_report_fields = ("classification", "diagnosis", "next_action", "diagnostics")
    if not isinstance(scenario_results, list) or not scenario_results:
        return {
            "check_id": "readiness",
            "status": "FAIL",
            "preopen_status_code": "READINESS_CONTRACT_INVALID",
            "details": f"readiness sem scenario_results validos ({readiness_manifest_path})",
            "next_step": "reexecutar verify_ovr_stab_g8_readiness.py para regenerar contrato completo",
        }
    for row in scenario_results:
        if not isinstance(row, dict):
            return {
                "check_id": "readiness",
                "status": "FAIL",
                "preopen_status_code": "READINESS_CONTRACT_INVALID",
                "details": f"readiness com scenario_results invalidos ({readiness_manifest_path})",
                "next_step": "corrigir geracao do readiness para emitir scenario_results como lista de objetos",
            }
        missing_fields = [field for field in required_report_fields if field not in row]
        if missing_fields:
            return {
                "check_id": "readiness",
                "status": "FAIL",
                "preopen_status_code": "READINESS_CONTRACT_INVALID",
                "details": f"readiness com campos ausentes em scenario_results: {','.join(missing_fields)}",
                "next_step": "regerar readiness com classificacao/diagnostico/next_action completos por cenario",
            }
    cen05_pass = False
    if isinstance(scenario_results, list):
        for row in scenario_results:
            if isinstance(row, dict) and str(row.get("scenario_id")) == "CEN-05" and str(row.get("status")) == "PASS":
                cen05_pass = True
                break
    if g8_ready and cen05_pass:
        return {
            "check_id": "readiness",
            "status": "PASS",
            "preopen_status_code": PREOPEN_CHECK_CODE_OK,
            "details": f"readiness consolidado aprovado ({readiness_manifest_path})",
            "next_step": "nenhum",
        }
    return {
        "check_id": "readiness",
        "status": "FAIL",
        "preopen_status_code": "READINESS_G8_OR_CEN05_FAILED",
        "details": f"readiness nao aprovado para G8/CEN-05 ({readiness_manifest_path})",
        "next_step": "reexecutar verify_ovr_stab_g8_readiness.py com evidencias de campo atualizadas",
    }


def _check_freshness(named_paths: Sequence[Tuple[str, Optional[Path]]], max_age_seconds: int) -> Dict[str, Any]:
    stale: List[str] = []
    now = time.time()
    for label, path in named_paths:
        if path is None or not path.exists():
            stale.append(f"{label}:missing")
            continue
        age = max(0, int(now - path.stat().st_mtime))
        if age > max_age_seconds:
            stale.append(f"{label}:stale:{age}s")
    if stale:
        return {
            "check_id": "freshness",
            "status": "FAIL",
            "preopen_status_code": "FRESHNESS_WINDOW_EXCEEDED",
            "details": f"artefatos fora da janela de pre-abertura ({max_age_seconds}s)",
            "stale": stale,
            "next_step": "regerar bundle/readiness/stress imediatamente antes da abertura",
        }
    return {
        "check_id": "freshness",
        "status": "PASS",
        "preopen_status_code": PREOPEN_CHECK_CODE_OK,
        "details": f"artefatos recentes (janela <= {max_age_seconds}s)",
        "stale": [],
        "next_step": "nenhum",
    }


def _build_operational_messages(checks: Sequence[Dict[str, Any]], preflight_ok: bool) -> List[str]:
    by_id = {str(item.get("check_id", "")): item for item in checks}
    lines: List[str] = []
    if preflight_ok:
        lines.append("PREOPEN-GO: CEN-05 liberado para abertura monitorada.")
        lines.append("Operacao: manter HUD/status endpoint visiveis e registrar checkpoint de 5min.")
        return lines
    lines.append("PREOPEN-BLOCK: CEN-05 bloqueado ate correcoes obrigatorias.")
    ordered_failures = ("artifacts", "thresholds", "commands", "bundle", "readiness", "env_doctor", "freshness")
    for check_id in ordered_failures:
        row = by_id.get(check_id, {})
        if row.get("status") != "FAIL":
            continue
        lines.append(f"{check_id.upper()}: {row.get('next_step', 'corrigir e revalidar')}")
    return lines


def _derive_preopen_status_code(checks: Sequence[Dict[str, Any]], preflight_ok: bool) -> str:
    if preflight_ok:
        return PREOPEN_STATUS_GO
    return PREOPEN_STATUS_BLOCKED


def _build_next_actions(checks: Sequence[Dict[str, Any]], preflight_ok: bool) -> List[Dict[str, Any]]:
    if preflight_ok:
        return [
            {
                "priority": 1,
                "check_id": "go-live",
                "status_code": PREOPEN_STATUS_GO,
                "action": "Iniciar abertura monitorada e registrar checkpoint operacional em 5 minutos.",
                "command": "python scripts/run_ovr_stab_field_qa.py",
                "exit_criteria": "HUD e endpoint de status ativos sem alertas criticos.",
            }
        ]
    failing_checks = [row for row in checks if row.get("status") != "PASS"]
    actions: List[Dict[str, Any]] = []
    for idx, row in enumerate(failing_checks, start=1):
        check_id = str(row.get("check_id", "unknown"))
        actions.append(
            {
                "priority": idx,
                "check_id": check_id,
                "status_code": str(row.get("preopen_status_code", "UNKNOWN")),
                "action": str(row.get("next_step", "corrigir e revalidar")),
                "command": CHECK_REMEDIATION_COMMANDS.get(check_id, "validar manualmente e repetir preflight"),
                "exit_criteria": f"{check_id} com status PASS no proximo verify_cen05_preflight.",
            }
        )
    actions.append(
        {
            "priority": len(actions) + 1,
            "check_id": "final_recheck",
            "status_code": PREOPEN_STATUS_BLOCKED,
            "action": "Reexecutar preflight estrito apos correcoes.",
            "command": "python scripts/verify_cen05_preflight.py --strict",
            "exit_criteria": "preflight_ok=true e preopen_status_code=PREOPEN_GO.",
        }
    )
    return actions


def _check_env_doctor(required_keys: Sequence[str]) -> Dict[str, Any]:
    missing_env = [key for key in required_keys if not str(os.environ.get(key, "")).strip()]
    invalid_paths: List[str] = []
    path_details: List[str] = []
    for key in REQUIRED_OPENING_PATH_KEYS:
        raw_value = str(os.environ.get(key, "")).strip()
        if not raw_value:
            continue
        target = Path(raw_value)
        if not target.exists():
            invalid_paths.append(key)
            path_details.append(f"{key}:missing:{target}")
            continue
        if target.is_dir():
            invalid_paths.append(key)
            path_details.append(f"{key}:expected_file_got_dir:{target}")
            continue
        if target.suffix.lower() != ".dll":
            invalid_paths.append(key)
            path_details.append(f"{key}:expected_dll:{target}")

    missing_scripts = [str(path) for path in REQUIRED_OPENING_SCRIPT_PATHS if not path.exists()]

    missing_dependencies: List[str] = []
    for dep_name, dep_kind, _desc in REQUIRED_RUNTIME_DEPENDENCIES:
        if dep_kind == "python":
            if shutil.which(dep_name) is None:
                missing_dependencies.append(f"{dep_name}:missing_executable")
        elif dep_kind == "python_module":
            if importlib.util.find_spec(dep_name) is None:
                missing_dependencies.append(f"{dep_name}:missing_module")

    system_ok = platform.system().lower() == "windows"
    problems: List[str] = []
    if missing_env:
        problems.append(f"vars ausentes: {', '.join(missing_env)}")
    if invalid_paths:
        problems.append(f"paths invalidos: {', '.join(invalid_paths)}")
    if missing_scripts:
        problems.append("scripts obrigatorios ausentes")
    if missing_dependencies:
        problems.append("dependencias runtime ausentes")
    if not system_ok:
        problems.append(f"sistema nao suportado: {platform.system()}")

    if problems:
        actions: List[Dict[str, str]] = []
        if missing_env:
            actions.append(
                {
                    "failure_code": "ENV_VARS_MISSING",
                    "cause": f"variaveis ausentes: {', '.join(missing_env)}",
                    "recommended_action": "Definir variaveis da sessao real no shell atual antes do preflight.",
                    "suggested_command": "set PROFIT_DLL_USER=... && set PROFIT_DLL_PASSWORD=... && set PQ_PROFIT_DLL_PATH=C:\\caminho\\ProfitChartTrading.dll",
                    "exit_criteria": "Todas as variaveis obrigatorias preenchidas e nao vazias.",
                }
            )
        if invalid_paths:
            actions.append(
                {
                    "failure_code": "OPENING_PATHS_INVALID",
                    "cause": f"paths invalidos: {', '.join(path_details or invalid_paths)}",
                    "recommended_action": "Corrigir variavel de path para apontar para a DLL real da sessao.",
                    "suggested_command": "set PQ_PROFIT_DLL_PATH=C:\\caminho\\ProfitChartTrading.dll",
                    "exit_criteria": "PQ_PROFIT_DLL_PATH aponta para arquivo .dll existente.",
                }
            )
        if missing_scripts:
            actions.append(
                {
                    "failure_code": "OPENING_SCRIPTS_MISSING",
                    "cause": f"scripts ausentes: {', '.join(missing_scripts)}",
                    "recommended_action": "Restaurar scripts obrigatorios no workspace antes da abertura.",
                    "suggested_command": "git status",
                    "exit_criteria": "Scripts obrigatorios resolvidos e presentes no repositorio local.",
                }
            )
        if missing_dependencies:
            actions.append(
                {
                    "failure_code": "OPENING_DEPENDENCIES_MISSING",
                    "cause": f"dependencias ausentes: {', '.join(missing_dependencies)}",
                    "recommended_action": "Instalar/ativar dependencias minimas no host de abertura.",
                    "suggested_command": "python -m pip install pytest",
                    "exit_criteria": "Executaveis/modulos obrigatorios detectados pelo env doctor.",
                }
            )
        if not system_ok:
            actions.append(
                {
                    "failure_code": "OPENING_OS_UNSUPPORTED",
                    "cause": f"host atual: {platform.system()}",
                    "recommended_action": "Executar preflight no host Windows homologado para abertura.",
                    "suggested_command": "python scripts/verify_cen05_preflight.py --strict",
                    "exit_criteria": "platform.system() = Windows no host operacional.",
                }
            )
        return {
            "check_id": "env_doctor",
            "status": "FAIL",
            "preopen_status_code": "ENV_DOCTOR_NOT_READY",
            "details": "; ".join(problems),
            "missing_env": missing_env,
            "invalid_paths": invalid_paths,
            "missing_dependencies": missing_dependencies,
            "missing_scripts": missing_scripts,
            "remediation_plan": actions,
            "next_step": "executar plano de correcao ENV_DOCTOR e revalidar preflight",
        }
    return {
        "check_id": "env_doctor",
        "status": "PASS",
        "preopen_status_code": PREOPEN_CHECK_CODE_OK,
        "details": "env doctor aprovado: variaveis/paths/dependencias minimas de abertura presentes",
        "missing_env": [],
        "invalid_paths": [],
        "missing_dependencies": [],
        "missing_scripts": [],
        "remediation_plan": [],
        "next_step": "nenhum",
    }


def _render_summary(
    path: Path,
    checks: List[Dict[str, Any]],
    preflight_ok: bool,
    inputs: Dict[str, str],
    preopen_status_code: str,
    next_actions: Sequence[Dict[str, Any]],
) -> None:
    operational_messages = _build_operational_messages(checks, preflight_ok)
    lines = [
        "# CEN-05 preflight validator",
        "",
        f"- preflight_ok: `{int(preflight_ok)}`",
        f"- preopen_status_code: `{preopen_status_code}`",
        f"- stress_manifest: `{inputs.get('stress_manifest', '') or 'not-found'}`",
        f"- commands_file: `{inputs.get('commands_file', '') or 'not-found'}`",
        f"- bundle_manifest: `{inputs.get('bundle_manifest', '') or 'not-found'}`",
        f"- readiness_manifest: `{inputs.get('readiness_manifest', '') or 'not-found'}`",
        "",
        "| check | status | preopen_status_code | details | next_step |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in checks:
        lines.append(
            f"| {row.get('check_id', '')} | {row.get('status', '')} | "
            f"{row.get('preopen_status_code', '')} | {row.get('details', '')} | {row.get('next_step', '')} |"
        )
    lines.append("")
    lines.append("## Mensagens operacionais")
    lines.append("")
    for msg in operational_messages:
        lines.append(f"- {msg}")
    lines.append("")
    lines.append("## Proximos passos operacionais")
    lines.append("")
    for action in next_actions:
        lines.append(
            f"- P{action.get('priority')} `{action.get('status_code')}` | "
            f"{action.get('check_id')}: {action.get('action')} | comando: `{action.get('command')}` | "
            f"criterio: {action.get('exit_criteria')}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"cen05-preflight-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    stress_manifest_path = _resolve_stress_manifest(args.stress_manifest)
    commands_file = _resolve_commands_file(args.commands_file)
    bundle_manifest_path = _resolve_bundle_manifest(args.bundle_manifest)
    readiness_manifest_path = _resolve_readiness_manifest(args.readiness_manifest)
    stress_manifest = _load_json(stress_manifest_path)
    bundle_manifest = _load_json(bundle_manifest_path)
    readiness_manifest = _load_json(readiness_manifest_path)

    checks = [
        _check_artifacts(stress_manifest_path),
        _check_thresholds(stress_manifest),
        _check_commands(commands_file),
        _check_bundle(bundle_manifest_path, bundle_manifest),
        _check_readiness(readiness_manifest_path, readiness_manifest),
        _check_env_doctor(REQUIRED_ENV_KEYS),
        _check_freshness(
            (
                ("stress_manifest", stress_manifest_path),
                ("commands_file", commands_file),
                ("bundle_manifest", bundle_manifest_path),
                ("readiness_manifest", readiness_manifest_path),
            ),
            max(60, int(args.max_age_seconds)),
        ),
    ]
    preflight_ok = all(row.get("status") == "PASS" for row in checks)
    preopen_status_code = _derive_preopen_status_code(checks, preflight_ok)
    next_actions = _build_next_actions(checks, preflight_ok)

    summary_md = out_dir / "summary.md"
    summary_manifest = out_dir / "summary.manifest.json"
    inputs = {
        "stress_manifest": str(stress_manifest_path) if stress_manifest_path else "",
        "commands_file": str(commands_file) if commands_file else "",
        "bundle_manifest": str(bundle_manifest_path) if bundle_manifest_path else "",
        "readiness_manifest": str(readiness_manifest_path) if readiness_manifest_path else "",
    }
    _render_summary(summary_md, checks, preflight_ok, inputs, preopen_status_code, next_actions)
    operational_messages = _build_operational_messages(checks, preflight_ok)
    payload = {
        "runner": "verify_cen05_preflight.py",
        "contract_version": PREOPEN_CONTRACT_VERSION,
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "preflight_ok": preflight_ok,
        "preopen_status_code": preopen_status_code,
        "checks": checks,
        "operational_messages": operational_messages,
        "next_actions": next_actions,
        "report_contract": {
            "checks_required_fields": ["check_id", "status", "preopen_status_code", "details", "next_step"],
            "next_actions_required_fields": [
                "priority",
                "check_id",
                "status_code",
                "action",
                "command",
                "exit_criteria",
            ],
        },
        "inputs": inputs,
        "artifacts": {"summary_md": str(summary_md), "summary_manifest": str(summary_manifest)},
    }
    summary_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    if args.strict and not preflight_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
