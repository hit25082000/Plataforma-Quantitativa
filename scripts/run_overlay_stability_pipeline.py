#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_BASE = ROOT / "distributor" / "logs"


@dataclass(frozen=True)
class PipelineStep:
    id: str
    script_relpath: str
    args: List[str]
    expected_manifest_relpath: str


STEPS: List[PipelineStep] = [
    PipelineStep(
        id="ovr_stab_qa_evidence",
        script_relpath="scripts/run_ovr_stab_qa_evidence.py",
        args=[],
        expected_manifest_relpath="summary.manifest.json",
    ),
    PipelineStep(
        id="ovr_stab_field_qa",
        script_relpath="scripts/run_ovr_stab_field_qa.py",
        args=[],
        expected_manifest_relpath="qa_session.manifest.json",
    ),
    PipelineStep(
        id="ocr_overlay_prerelease_sanity",
        script_relpath="scripts/run_ocr_overlay_prerelease_sanity.py",
        args=[],
        expected_manifest_relpath="report.manifest.json",
    ),
    PipelineStep(
        id="overlay_ws_stress_regression",
        script_relpath="scripts/run_overlay_ws_stress_regression.py",
        args=[],
        expected_manifest_relpath="summary.manifest.json",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline local de QA/pre-release para overlay stability.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Pasta final do pipeline.")
    parser.add_argument("--stop-on-fail", action="store_true", default=False)
    return parser.parse_args()


def _manifest_overall_ok(payload: Dict[str, object]) -> bool:
    raw = payload.get("overall_ok")
    return bool(raw) if isinstance(raw, bool) else False


def _step_output_dir(pipeline_dir: Path, step: PipelineStep) -> Path:
    return pipeline_dir / "steps" / step.id


def _build_command(step: PipelineStep, out_dir: Path) -> List[str]:
    script_path = ROOT / step.script_relpath
    cmd = [sys.executable, str(script_path), "--out-dir", str(out_dir)]
    cmd.extend(step.args)
    return cmd


def _resolve_manifest_path(step_dir: Path, expected_relpath: str) -> Path:
    direct = step_dir / expected_relpath
    if direct.exists():
        return direct
    candidates = sorted(step_dir.glob(f"**/{expected_relpath}"))
    return candidates[0] if candidates else direct


def _run_step(step: PipelineStep, pipeline_dir: Path) -> Dict[str, object]:
    step_dir = _step_output_dir(pipeline_dir, step)
    step_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = step_dir / "stdout.log"
    stderr_path = step_dir / "stderr.log"
    cmd = _build_command(step, step_dir)

    started = time.time()
    with stdout_path.open("w", encoding="utf-8") as out_f, stderr_path.open("w", encoding="utf-8") as err_f:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=out_f, stderr=err_f, check=False, shell=False)
    elapsed = round(time.time() - started, 3)

    expected_manifest = _resolve_manifest_path(step_dir, step.expected_manifest_relpath)
    manifest_found = expected_manifest.exists()
    manifest_payload: Dict[str, object] = {}
    manifest_parse_error = ""
    if manifest_found:
        try:
            parsed = json.loads(expected_manifest.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                manifest_payload = parsed
            else:
                manifest_parse_error = "manifest nao eh objeto json"
        except (OSError, json.JSONDecodeError) as exc:
            manifest_parse_error = f"manifest invalido: {exc}"

    manifest_ok = _manifest_overall_ok(manifest_payload) if manifest_payload else False
    status = "ok" if int(proc.returncode) == 0 and manifest_ok else "fail"
    if not manifest_found:
        status = "fail"

    return {
        "id": step.id,
        "script": step.script_relpath,
        "command": cmd,
        "exit_code": int(proc.returncode),
        "elapsed_s": elapsed,
        "status": status,
        "step_dir": str(step_dir),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "manifest_path": str(expected_manifest),
        "manifest_found": manifest_found,
        "manifest_parse_error": manifest_parse_error,
        "manifest_overall_ok": manifest_ok,
    }


def _write_report_md(path: Path, rows: List[Dict[str, object]], overall_ok: bool) -> None:
    lines: List[str] = []
    lines.append("# Overlay Stability Pipeline Report")
    lines.append("")
    lines.append(f"- overall_ok: `{int(overall_ok)}`")
    lines.append(f"- total_steps: `{len(rows)}`")
    lines.append(f"- failed_steps: `{sum(1 for row in rows if row['status'] != 'ok')}`")
    lines.append("")
    lines.append("| step | status | exit_code | manifest_ok | elapsed_s | manifest_path |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['status']} | {row['exit_code']} | "
            f"{int(bool(row['manifest_overall_ok']))} | {row['elapsed_s']} | {row['manifest_path']} |"
        )

    failed = [row for row in rows if row["status"] != "ok"]
    if failed:
        lines.append("")
        lines.append("## Failures")
        lines.append("")
        for row in failed:
            detail_parts: List[str] = []
            if not bool(row["manifest_found"]):
                detail_parts.append("manifest ausente")
            if bool(row["manifest_parse_error"]):
                detail_parts.append(str(row["manifest_parse_error"]))
            if int(row["exit_code"]) != 0:
                detail_parts.append(f"exit_code={row['exit_code']}")
            if not bool(row["manifest_overall_ok"]):
                detail_parts.append("manifest_overall_ok=0")
            lines.append(f"- `{row['id']}`: " + "; ".join(detail_parts))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    started_at = time.time()
    out_dir = args.out_dir or (DEFAULT_OUT_BASE / f"overlay-stability-pipeline-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, object]] = []
    for step in STEPS:
        row = _run_step(step, out_dir)
        results.append(row)
        if args.stop_on_fail and row["status"] != "ok":
            break

    overall_ok = all(row["status"] == "ok" for row in results) and len(results) == len(STEPS)
    report_md = out_dir / "pipeline_report.md"
    manifest = out_dir / "pipeline_manifest.json"
    _write_report_md(report_md, results, overall_ok)
    manifest.write_text(
        json.dumps(
            {
                "runner": "run_overlay_stability_pipeline.py",
                "started_at_epoch_s": started_at,
                "finished_at_epoch_s": time.time(),
                "overall_ok": overall_ok,
                "steps": results,
                "artifacts": {
                    "pipeline_report_md": str(report_md),
                    "pipeline_manifest": str(manifest),
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Wrote: {report_md}")
    print(f"Wrote: {manifest}")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
