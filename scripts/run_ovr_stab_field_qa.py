#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"


@dataclass(frozen=True)
class QaTask:
    id: str
    title: str
    objective: str
    requires_api: bool
    requires_trace: bool
    requires_real_session: bool
    requires_multi_monitor: bool
    requires_high_load: bool


QA_TASKS: List[QaTask] = [
    QaTask(
        id="OVR-STAB-QA-02",
        title="Zoom/eixo vertical com transicao controlada",
        objective="Verificar estados SUSPECT/RECALIBRATING/FROZEN em mudanca de escala.",
        requires_api=True,
        requires_trace=True,
        requires_real_session=True,
        requires_multi_monitor=False,
        requires_high_load=False,
    ),
    QaTask(
        id="OVR-STAB-QA-03",
        title="OCR ruim com degradacao controlada",
        objective="Verificar preservacao de lastStableAxis com contraste/oclusao parcial.",
        requires_api=True,
        requires_trace=True,
        requires_real_session=True,
        requires_multi_monitor=False,
        requires_high_load=False,
    ),
    QaTask(
        id="OVR-STAB-QA-04",
        title="Multi-monitor e DPI",
        objective="Validar bounds corretos em 100/125/150 e troca de monitor.",
        requires_api=True,
        requires_trace=True,
        requires_real_session=True,
        requires_multi_monitor=True,
        requires_high_load=False,
    ),
    QaTask(
        id="OVR-STAB-QA-05",
        title="Carga com muitos targets/histograma",
        objective="Verificar responsividade sem crescimento de fila em stress operacional.",
        requires_api=True,
        requires_trace=True,
        requires_real_session=True,
        requires_multi_monitor=False,
        requires_high_load=True,
    ),
]


def _http_json(url: str, timeout_seconds: float) -> Dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "ovr-stab-field-qa/1.0"},
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


def _latest_evidence_dirs(limit: int = 12) -> List[str]:
    if not LOGS_DIR.exists():
        return []
    prefixes = (
        "ovr-stab-qa-evidence-",
        "m6-m7-evidence-",
        "m9-rag-operational-evidence-",
        "vp-sato-performance-",
    )
    rows: List[tuple[float, Path]] = []
    for entry in LOGS_DIR.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name.lower()
        if any(name.startswith(prefix) for prefix in prefixes):
            rows.append((entry.stat().st_mtime, entry.resolve()))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [str(path) for _, path in rows[:limit]]


def _probe(base_url: str, timeout_seconds: float, trace_path: Path) -> Dict[str, Any]:
    health = _http_json(f"{base_url.rstrip('/')}/health", timeout_seconds)
    debug = _http_json(f"{base_url.rstrip('/')}/api/ocr-overlay/debug", timeout_seconds)
    status = _http_json(f"{base_url.rstrip('/')}/api/ocr-overlay/status", timeout_seconds)
    return {
        "base_url": base_url.rstrip("/"),
        "health_ok": bool(isinstance(health, dict)),
        "debug_ok": bool(isinstance(debug, dict)),
        "status_ok": bool(isinstance(status, dict)),
        "trace_path": str(trace_path),
        "trace_exists": trace_path.exists(),
        "trace_size_bytes": trace_path.stat().st_size if trace_path.exists() else 0,
        "latest_evidence_dirs": _latest_evidence_dirs(),
    }


def _task_state(task: QaTask, probe: Dict[str, Any], assume_manual_ready: bool) -> Dict[str, Any]:
    blockers: List[str] = []
    if task.requires_api and not bool(probe["health_ok"] and probe["debug_ok"] and probe["status_ok"]):
        blockers.append("api_indisponivel: health/debug/status nao responderam")
    if task.requires_trace and not bool(probe["trace_exists"]):
        blockers.append(f"trace_ausente: {probe['trace_path']}")
    if task.requires_real_session and not assume_manual_ready:
        blockers.append("sessao_real_nao_confirmada: usar --assume-manual-ready para registrar sessao assistida")
    if task.requires_multi_monitor:
        blockers.append("requer_multi_monitor: executar em 100/125/150 com captura manual")
    if task.requires_high_load:
        blockers.append("requer_carga_real: validar throughput com VP/targets/histograma ativos")

    ready = len(blockers) == 0
    return {
        "id": task.id,
        "title": task.title,
        "objective": task.objective,
        "ready_for_session": ready,
        "state": "ready" if ready else "blocked",
        "blockers": blockers,
    }


def _write_summary_md(path: Path, probe: Dict[str, Any], tasks: List[Dict[str, Any]]) -> None:
    ready_count = sum(1 for item in tasks if bool(item["ready_for_session"]))
    lines: List[str] = [
        "# OVR STAB QA field execution (manual assisted)",
        "",
        f"- base_url: `{probe['base_url']}`",
        f"- api_health: `{int(bool(probe['health_ok']))}`",
        f"- api_debug: `{int(bool(probe['debug_ok']))}`",
        f"- api_status: `{int(bool(probe['status_ok']))}`",
        f"- trace_exists: `{int(bool(probe['trace_exists']))}`",
        f"- trace_path: `{probe['trace_path']}`",
        f"- tasks_ready: `{ready_count}/{len(tasks)}`",
        "",
        "## Tasks",
        "",
        "| id | state | title | blockers |",
        "| --- | --- | --- | --- |",
    ]
    for item in tasks:
        blockers = "; ".join(str(x) for x in item["blockers"]) if item["blockers"] else "none"
        lines.append(f"| {item['id']} | {item['state']} | {item['title']} | {blockers} |")
    lines.append("")
    lines.append("## Evidence dirs discovered")
    lines.append("")
    for evidence_dir in probe["latest_evidence_dirs"]:
        lines.append(f"- `{evidence_dir}`")
    if not probe["latest_evidence_dirs"]:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_commands_md(path: Path, probe: Dict[str, Any], out_dir: Path) -> None:
    base = str(probe["base_url"])
    trace = str(probe["trace_path"])
    summary_trace = str((out_dir / "trace_window.summary.json").resolve())
    lines = [
        "# Command checklist per session",
        "",
        "## 1) Pre-flight probes",
        "",
        f"python scripts/run_ovr_stab_field_qa.py --base-url {base} --trace-path \"{trace}\" --out-dir \"{out_dir}\"",
        "",
        "## 2) Trace window capture (60s)",
        "",
        f"python scripts/collect_ocr_overlay_trace_60s.py --duration-sec 60 --trace-path \"{trace}\" --summary-out \"{summary_trace}\"",
        "",
        "## 3) Optional local suites (mocked)",
        "",
        "python scripts/run_ovr_stab_qa_evidence.py",
        "",
        "## 4) Session notes template",
        "",
        "- registrar ativo, horario, monitor/DPI, cenario, resultado e anexos",
        "- preencher o arquivo qa_session.manifest.json desta pasta",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automacao de QA de campo OVR-STAB-QA-02/03/04/05.")
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--trace-path", type=str, default="")
    parser.add_argument("--timeout-seconds", type=float, default=2.5)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--assume-manual-ready", action="store_true", default=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"ovr-stab-field-qa-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    trace_path = _resolve_trace_path(args.trace_path)
    probe = _probe(args.base_url, float(args.timeout_seconds), trace_path)
    tasks = [_task_state(task, probe, bool(args.assume_manual_ready)) for task in QA_TASKS]

    summary_md = out_dir / "summary.md"
    commands_md = out_dir / "commands.md"
    manifest_path = out_dir / "qa_session.manifest.json"

    _write_summary_md(summary_md, probe, tasks)
    _write_commands_md(commands_md, probe, out_dir)

    ready_count = sum(1 for item in tasks if bool(item["ready_for_session"]))
    payload = {
        "runner": "run_ovr_stab_field_qa.py",
        "scope": "manual-assisted-field-qa",
        "started_at_epoch_s": time.time(),
        "probe": probe,
        "tasks": tasks,
        "ready_count": ready_count,
        "total_tasks": len(tasks),
        "artifacts": {
            "summary_md": str(summary_md),
            "commands_md": str(commands_md),
            "qa_session_manifest": str(manifest_path),
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_md}")
    print(f"Wrote: {commands_md}")
    print(f"Wrote: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
