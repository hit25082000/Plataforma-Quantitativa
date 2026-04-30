#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"

OPERATOR_CHECKLIST = [
    "Confirmar Profit aberto no ativo alvo (WINFUT/mini) e horario de pregao.",
    "Confirmar overlay OCR ativo e visivel no monitor de execucao.",
    "Executar comando de captura assistida desta pasta (commands.md).",
    "Durante 60-120s: alternar zoom/eixo e observar estados SUSPECT/RECALIBRATING/FROZEN.",
    "Durante a janela: registrar evento de degradacao OCR (contraste/oclusao parcial) se aplicavel.",
    "Ao final da janela: salvar anotacoes manuais em operator_notes.md.",
    "Anexar prints/logs adicionais se houver falha perceptivel de UI ou congelamento.",
]


def _http_json(url: str, timeout_seconds: float) -> Dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "pregao-assisted-session/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else None
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _resolve_trace_path(explicit_path: str) -> Path:
    chosen = (explicit_path or os.environ.get("PQ_OCR_TRACE_PATH") or "").strip()
    if chosen:
        return Path(chosen).resolve()
    return (LOGS_DIR / "ocr_overlay_trace.jsonl").resolve()


def _duration_sec(raw: int) -> int:
    value = int(raw)
    if value < 60 or value > 120:
        raise argparse.ArgumentTypeError("duration must be between 60 and 120 seconds")
    return value


def _collect_status_snapshot(base_url: str, timeout_seconds: float) -> Dict[str, Any]:
    health = _http_json(f"{base_url.rstrip('/')}/health", timeout_seconds)
    debug = _http_json(f"{base_url.rstrip('/')}/api/ocr-overlay/debug", timeout_seconds)
    status = _http_json(f"{base_url.rstrip('/')}/api/ocr-overlay/status", timeout_seconds)
    return {
        "base_url": base_url.rstrip("/"),
        "health_ok": bool(isinstance(health, dict)),
        "debug_ok": bool(isinstance(debug, dict)),
        "status_ok": bool(isinstance(status, dict)),
        "health": health or {},
        "debug": debug or {},
        "status": status or {},
    }


def _collect_config_snapshot(trace_path: Path, duration_sec: int, dry_run: bool) -> Dict[str, Any]:
    env_keys = [
        "PQ_OCR_TRACE_PATH",
        "PQ_PROFIT_DLL_PATH",
        "PROFIT_TICKER",
        "PROFIT_BOLSA",
        "SHM_ENABLED",
        "SHM_MAPPING_NAME",
        "SHM_SIZE_MB",
    ]
    scripts = [
        ROOT / "scripts" / "run_ovr_stab_field_qa.py",
        ROOT / "scripts" / "collect_ocr_overlay_trace_60s.py",
        ROOT / "scripts" / "run_m6_m7_evidence.py",
        ROOT / "scripts" / "run-m6-m7-evidence.ps1",
    ]
    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "python": sys.version,
        },
        "session": {
            "duration_sec": int(duration_sec),
            "dry_run": bool(dry_run),
            "trace_path": str(trace_path),
            "trace_exists": trace_path.exists(),
            "trace_size_bytes": trace_path.stat().st_size if trace_path.exists() else 0,
        },
        "env": {key: os.environ.get(key, "") for key in env_keys},
        "scripts_presence": {str(path.relative_to(ROOT)): path.exists() for path in scripts},
    }


def _write_operator_checklist(path: Path, duration_sec: int) -> None:
    lines = [
        "# Checklist do operador (sessao assistida)",
        "",
        f"- Janela alvo: `{duration_sec}s`",
        "- Objetivo: coletar evidencias de trace/status/config sem depender de execucao automatica integral.",
        "",
        "## Acoes",
        "",
    ]
    for index, item in enumerate(OPERATOR_CHECKLIST, start=1):
        lines.append(f"{index}. [ ] {item}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_commands(path: Path, *, out_dir: Path, base_url: str, trace_path: Path, duration_sec: int) -> None:
    trace_summary = out_dir / "trace_window.summary.json"
    lines = [
        "# Sequencia de comandos (pregao assistido)",
        "",
        "## 1) Pre-flight field QA",
        f"python scripts/run_ovr_stab_field_qa.py --base-url {base_url} --trace-path \"{trace_path}\" --out-dir \"{out_dir / 'field_qa_probe'}\" --assume-manual-ready",
        "",
        "## 2) Janela curta de trace",
        f"python scripts/collect_ocr_overlay_trace_60s.py --duration-sec {duration_sec} --trace-path \"{trace_path}\" --summary-out \"{trace_summary}\"",
        "",
        "## 3) Opcional: baseline consolidado M6/M7",
        f"powershell -ExecutionPolicy Bypass -File scripts/run-m6-m7-evidence.ps1 -OutDir \"{out_dir / 'm6_m7_reference'}\" -HftDurationSeconds {duration_sec} -SessionSeconds {duration_sec} -FailOnAny:$false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_operator_notes_template(path: Path) -> None:
    lines = [
        "# Notas do operador",
        "",
        "- ativo:",
        "- horario_inicio:",
        "- horario_fim:",
        "- monitor_dpi:",
        "- comportamento_overlay:",
        "- observacoes_falha:",
        "- anexos:",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepara sessao guiada de coleta assistida para pregao real.")
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--trace-path", type=str, default="")
    parser.add_argument("--duration-sec", type=_duration_sec, default=90)
    parser.add_argument("--timeout-seconds", type=float, default=2.5)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"pregao-assisted-session-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    trace_path = _resolve_trace_path(args.trace_path)
    status_snapshot = _collect_status_snapshot(args.base_url, float(args.timeout_seconds))
    config_snapshot = _collect_config_snapshot(trace_path, int(args.duration_sec), bool(args.dry_run))

    status_path = out_dir / "status_snapshot.json"
    config_path = out_dir / "config_snapshot.json"
    checklist_path = out_dir / "operator_checklist.md"
    commands_path = out_dir / "commands.md"
    notes_path = out_dir / "operator_notes.md"
    manifest_path = out_dir / "session.manifest.json"

    status_path.write_text(json.dumps(status_snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    config_path.write_text(json.dumps(config_snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_operator_checklist(checklist_path, int(args.duration_sec))
    _write_commands(
        commands_path,
        out_dir=out_dir,
        base_url=status_snapshot["base_url"],
        trace_path=trace_path,
        duration_sec=int(args.duration_sec),
    )
    _write_operator_notes_template(notes_path)

    command_preview = [
        [sys.executable, "scripts/run_ovr_stab_field_qa.py", "--assume-manual-ready"],
        [sys.executable, "scripts/collect_ocr_overlay_trace_60s.py", f"--duration-sec={int(args.duration_sec)}"],
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/run-m6-m7-evidence.ps1", "-FailOnAny:$false"],
    ]
    if not bool(args.dry_run):
        for command in command_preview:
            try:
                subprocess.run(command, cwd=str(ROOT), check=False, shell=False)
            except OSError:
                # Nao aborta a preparacao de evidencia por indisponibilidade de runtime.
                pass

    manifest = {
        "runner": "run_pregao_assisted_session.py",
        "scope": "pregao-assisted-session",
        "started_at_epoch_s": time.time(),
        "dry_run": bool(args.dry_run),
        "operator_window_seconds": int(args.duration_sec),
        "status_snapshot": status_snapshot,
        "config_snapshot": config_snapshot,
        "operator_checklist": OPERATOR_CHECKLIST,
        "command_preview": command_preview,
        "artifacts": {
            "status_snapshot_json": str(status_path),
            "config_snapshot_json": str(config_path),
            "operator_checklist_md": str(checklist_path),
            "commands_md": str(commands_path),
            "operator_notes_md": str(notes_path),
            "session_manifest_json": str(manifest_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {status_path}")
    print(f"Wrote: {config_path}")
    print(f"Wrote: {checklist_path}")
    print(f"Wrote: {commands_path}")
    print(f"Wrote: {notes_path}")
    print(f"Wrote: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
