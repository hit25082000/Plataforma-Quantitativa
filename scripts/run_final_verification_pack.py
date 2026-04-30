#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "distributor" / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pacote unico de verificacao final backend/frontend/tauri/scripts."
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--field-report", type=Path, default=None)
    parser.add_argument("--smoke", action="store_true", default=False)
    parser.add_argument("--strict", action="store_true", default=False)
    parser.add_argument("--continue-on-failure", action="store_true", default=False)
    return parser.parse_args()


def _run(cmd: List[str], cwd: Path, out_dir: Path, step_id: str) -> Dict[str, Any]:
    stdout_log = out_dir / f"{step_id}.stdout.log"
    stderr_log = out_dir / f"{step_id}.stderr.log"
    started = time.time()
    resolved_cmd = _resolve_executable(cmd)
    with stdout_log.open("w", encoding="utf-8") as out_f, stderr_log.open("w", encoding="utf-8") as err_f:
        proc = subprocess.run(resolved_cmd, cwd=str(cwd), shell=False, check=False, stdout=out_f, stderr=err_f)
    return {
        "id": step_id,
        "command": resolved_cmd,
        "exit_code": int(proc.returncode),
        "ok": int(proc.returncode) == 0,
        "elapsed_s": round(time.time() - started, 3),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }


def _resolve_executable(cmd: List[str]) -> List[str]:
    if not cmd:
        return cmd
    executable = cmd[0]
    if Path(executable).exists():
        return cmd
    resolved = shutil.which(executable)
    if resolved:
        return [resolved, *cmd[1:]]
    if os.name == "nt" and "." not in Path(executable).name:
        for ext in (".exe", ".cmd", ".bat"):
            resolved = shutil.which(f"{executable}{ext}")
            if resolved:
                return [resolved, *cmd[1:]]
    return cmd


def _build_plan(args: argparse.Namespace, out_dir: Path) -> List[Dict[str, Any]]:
    stress_out = out_dir / "stress"
    qa_out = out_dir / "qa"
    steps: List[Dict[str, Any]] = []

    if args.smoke:
        backend_cmd = [
            sys.executable,
            "-m",
            "unittest",
            "distributor.tests.test_ocr_overlay_audit",
        ]
        frontend_cmd = [
            "npm",
            "--prefix",
            "frontend",
            "run",
            "test",
            "--",
            "overlayUpdateCompat",
        ]
        tauri_cmds = [
            {
                "id": "step_03_tauri_check",
                "cmd": ["cargo", "check", "--manifest-path", "app/src-tauri/Cargo.toml"],
                "required": True,
            }
        ]
        stress_cmd = [
            sys.executable,
            "scripts/run_overlay_ws_stress_regression.py",
            "--out-dir",
            str(stress_out),
        ]
    else:
        backend_cmd = [
            sys.executable,
            "-m",
            "unittest",
            "distributor.tests.test_message_router_ui_aggregator",
            "distributor.tests.test_ocr_overlay_audit",
            "distributor.tests.test_profit_ocr_service",
            "distributor.tests.test_vp_overlay_consolidator",
            "distributor.tests.test_websocket_vp_overlay_endpoints",
            "distributor.tests.test_run_overlay_ws_stress_regression",
            "distributor.tests.test_run_ovr_stab_qa_evidence",
            "distributor.tests.test_verify_ovr_stab_g8_readiness",
        ]
        frontend_cmd = [
            "npm",
            "--prefix",
            "frontend",
            "run",
            "test",
            "--",
            "OverlayPage",
            "useProfitOverlay",
            "overlayUpdateCompat",
            "overlayRenderDiff",
        ]
        tauri_cmds = [
            {
                "id": "step_03_tauri_tests",
                "cmd": ["cargo", "test", "--manifest-path", "app/src-tauri/Cargo.toml"],
                "required": True,
            },
            {
                "id": "step_04_tauri_check",
                "cmd": ["cargo", "check", "--manifest-path", "app/src-tauri/Cargo.toml"],
                "required": True,
            },
        ]
        stress_cmd = [
            sys.executable,
            "scripts/run_overlay_ws_stress_regression.py",
            "--out-dir",
            str(stress_out),
        ]

    steps.append({"id": "step_01_backend_tests", "cmd": backend_cmd, "required": True})
    steps.append({"id": "step_02_frontend_tests", "cmd": frontend_cmd, "required": True})
    steps.extend(tauri_cmds)
    steps.append({"id": "step_05_stress", "cmd": stress_cmd, "required": True})
    steps.append(
        {
            "id": "step_06_qa_evidence",
            "cmd": [
                sys.executable,
                "scripts/run_ovr_stab_qa_evidence.py",
                "--mode",
                "local",
                "--strict",
                "--cen05-stress-manifest",
                str(stress_out / "summary.manifest.json"),
                "--out-dir",
                str(qa_out),
            ],
            "required": True,
        }
    )

    readiness_cmd = [
        sys.executable,
        "scripts/verify_ovr_stab_g8_readiness.py",
        "--qa-manifest",
        str(qa_out / "summary.manifest.json"),
        "--stress-manifest",
        str(stress_out / "summary.manifest.json"),
    ]
    if args.field_report is not None:
        readiness_cmd.extend(["--field-report", str(args.field_report.resolve()), "--strict"])
        readiness_required = True
    else:
        readiness_required = False
    steps.append({"id": "step_07_readiness", "cmd": readiness_cmd, "required": readiness_required})
    if args.field_report is not None:
        steps.append(
            {
                "id": "step_08_cen04_matrix_audit",
                "cmd": [
                    sys.executable,
                    "scripts/check_cen04_monitor_dpi_matrix.py",
                    "--strict",
                    "--field-report",
                    str(args.field_report.resolve()),
                    "--out-dir",
                    str(out_dir / "cen04-matrix-audit"),
                ],
                "required": True,
            }
        )
    return steps


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or (LOGS_DIR / f"final-verification-pack-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    steps_plan = _build_plan(args, out_dir)
    steps_result: List[Dict[str, Any]] = []
    interrupted_on_required_failure = False
    for step in steps_plan:
        result = _run(step["cmd"], ROOT, out_dir, step["id"])
        result["required"] = bool(step["required"])
        result["executed"] = True
        steps_result.append(result)
        if not result["ok"] and step["required"] and not args.continue_on_failure:
            interrupted_on_required_failure = True
            break

    executed_ids = {row["id"] for row in steps_result}
    for step in steps_plan:
        if step["id"] in executed_ids:
            continue
        steps_result.append(
            {
                "id": step["id"],
                "command": step["cmd"],
                "required": bool(step["required"]),
                "executed": False,
                "ok": False,
                "exit_code": None,
                "elapsed_s": 0.0,
                "stdout_log": "",
                "stderr_log": "",
                "skipped_reason": "pipeline_interrupted_after_required_failure",
            }
        )

    required_failed = [s for s in steps_result if s.get("required") and s.get("executed") and not s.get("ok")]
    strict_failed = [s for s in steps_result if s.get("executed") and not s.get("ok")]
    skipped_required = [s for s in steps_result if s.get("required") and not s.get("executed")]
    skipped_optional = [s for s in steps_result if (not s.get("required")) and not s.get("executed")]
    payload = {
        "runner": "run_final_verification_pack.py",
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "smoke" if args.smoke else "full",
        "field_report": str(args.field_report.resolve()) if args.field_report else "",
        "strict": bool(args.strict),
        "continue_on_failure": bool(args.continue_on_failure),
        "interrupted_on_required_failure": interrupted_on_required_failure,
        "required_ok": len(required_failed) == 0,
        "overall_ok": len(strict_failed if args.strict else required_failed) == 0,
        "required_failed_count": len(required_failed),
        "strict_failed_count": len(strict_failed),
        "skipped_required_count": len(skipped_required),
        "skipped_optional_count": len(skipped_optional),
        "steps": steps_result,
    }
    summary_manifest = out_dir / "summary.manifest.json"
    summary_md = out_dir / "summary.md"
    summary_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Final Verification Pack",
        "",
        f"- mode: `{payload['mode']}`",
        f"- required_ok: `{int(payload['required_ok'])}`",
        f"- overall_ok: `{int(payload['overall_ok'])}`",
        f"- interrupted_on_required_failure: `{int(payload['interrupted_on_required_failure'])}`",
        f"- required_failed_count: `{payload['required_failed_count']}`",
        f"- strict_failed_count: `{payload['strict_failed_count']}`",
        f"- skipped_required_count: `{payload['skipped_required_count']}`",
        f"- skipped_optional_count: `{payload['skipped_optional_count']}`",
        "",
        "## Steps",
        "",
    ]
    for row in steps_result:
        if not row.get("executed"):
            lines.append(
                f"- {row['id']}: executed=`0` required=`{int(bool(row['required']))}` ok=`0` skipped_reason=`{row.get('skipped_reason', 'n/a')}`"
            )
        else:
            lines.append(
                f"- {row['id']}: executed=`1` ok=`{int(bool(row['ok']))}` required=`{int(bool(row['required']))}` exit_code=`{row['exit_code']}` elapsed_s=`{row['elapsed_s']}`"
            )
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote: {summary_md}")
    print(f"Wrote: {summary_manifest}")
    return 0 if payload["overall_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
