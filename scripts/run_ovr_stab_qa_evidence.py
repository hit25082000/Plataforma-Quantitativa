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
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent

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
]

OVR_TARGETS = ["OVR-STAB-QA-01", "OVR-STAB-QA-02", "OVR-STAB-QA-03", "OVR-STAB-QA-04", "OVR-STAB-QA-05", "OVR-STAB-OBS-09"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--stop-on-fail", action="store_true", default=False)
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
    write_summary_csv(summary_csv, results)
    write_summary_md(summary_md, results, ovr_status, overall_ok)

    manifest = {
        "started_at_epoch_s": started,
        "finished_at_epoch_s": time.time(),
        "overall_ok": overall_ok,
        "runner": "run_ovr_stab_qa_evidence.py",
        "scope": "local-tests-no-profit-session",
        "results": results,
        "ovr_status": ovr_status,
        "artifacts": {
            "summary_csv": str(summary_csv),
            "summary_md": str(summary_md),
            "summary_manifest": str(summary_manifest),
        },
    }
    summary_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    if not overall_ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
