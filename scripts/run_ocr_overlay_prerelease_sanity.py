#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: str
    detail: str


REQUIRED_FILES: Tuple[Tuple[str, str], ...] = (
    ("resource", "app/src-tauri/resources/profit_ocr_service.py"),
    ("resource", "app/src-tauri/resources/ocr_overlay_audit.py"),
    ("resource", "app/src-tauri/resources/engine.exe"),
    ("resource", "app/src-tauri/resources/distributor.exe"),
    ("resource", "app/src-tauri/resources/ProfitDLL.dll"),
    ("resource", "app/src-tauri/resources/ProfitDLL64.dll"),
    ("resource", "app/src-tauri/resources/libzmq-mt-4_3_5.dll"),
    ("resource", "app/src-tauri/resources/sounds/wall.wav"),
    ("resource", "app/src-tauri/resources/sounds/breakout.wav"),
    ("contract", "docs/contracts/vp-overlay-v1.json"),
    ("fixture", "docs/contracts/fixtures/vp-overlay-demo.json"),
    ("qa-script", "scripts/run_ovr_stab_qa_evidence.py"),
    ("qa-script", "scripts/run_ovr_stab_field_qa.py"),
    ("qa-script", "scripts/collect_ocr_overlay_trace_60s.py"),
    ("qa-script", "scripts/sync-profit-ocr-to-tauri-resources.ps1"),
    ("qa-test", "distributor/tests/test_profit_ocr_service.py"),
    ("qa-test", "distributor/tests/test_ocr_overlay_audit.py"),
    ("qa-test", "distributor/tests/test_vp_overlay_contract.py"),
    ("qa-test", "distributor/tests/test_websocket_vp_overlay_endpoints.py"),
    ("qa-test", "distributor/tests/test_vp_ocr_enrich.py"),
)

CRITICAL_BUNDLE_ENTRIES: Tuple[str, ...] = (
    "resources/profit_ocr_service.py",
    "resources/profit_ocr_service.exe",
    "resources/engine.exe",
    "resources/distributor.exe",
    "resources/ProfitDLL.dll",
    "resources/ProfitDLL64.dll",
    "resources/libzmq-mt-4_3_5.dll",
    "resources/sounds/wall.wav",
    "resources/sounds/breakout.wav",
)

SYNC_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("distributor/profit_ocr_service.py", "app/src-tauri/resources/profit_ocr_service.py"),
    ("distributor/ocr_overlay_audit.py", "app/src-tauri/resources/ocr_overlay_audit.py"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanity pre-release do overlay OCR.")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "logs" / "pre-release")
    parser.add_argument("--fail-on-warning", action="store_true", default=False)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def check_required_files() -> List[CheckResult]:
    rows: List[CheckResult] = []
    for group, rel in REQUIRED_FILES:
        full = ROOT / rel
        if full.exists():
            rows.append(CheckResult(f"presence:{rel}", "ok", f"{group} presente"))
        else:
            rows.append(CheckResult(f"presence:{rel}", "fail", f"{group} ausente"))
    return rows


def check_sync_pairs() -> List[CheckResult]:
    rows: List[CheckResult] = []
    for src_rel, dst_rel in SYNC_PAIRS:
        src = ROOT / src_rel
        dst = ROOT / dst_rel
        if not src.exists() or not dst.exists():
            rows.append(CheckResult(f"sync:{src_rel}->{dst_rel}", "fail", "origem ou destino ausente"))
            continue
        src_hash = file_sha256(src)
        dst_hash = file_sha256(dst)
        if src_hash == dst_hash:
            rows.append(CheckResult(f"sync:{src_rel}->{dst_rel}", "ok", "conteudo sincronizado"))
        else:
            rows.append(
                CheckResult(
                    f"sync:{src_rel}->{dst_rel}",
                    "fail",
                    f"hash diverge src={src_hash[:12]} dst={dst_hash[:12]}",
                )
            )
    return rows


def load_tauri_bundle_resources() -> Tuple[List[str], List[CheckResult]]:
    conf_path = ROOT / "app/src-tauri/tauri.conf.json"
    if not conf_path.exists():
        return [], [CheckResult("bundle:tauri-conf", "fail", "tauri.conf.json ausente")]

    try:
        conf = json.loads(conf_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [CheckResult("bundle:tauri-conf", "fail", f"json invalido: {exc}")]

    bundle = conf.get("bundle")
    if not isinstance(bundle, dict):
        return [], [CheckResult("bundle:section", "fail", "secao bundle ausente")]
    resources = bundle.get("resources")
    if not isinstance(resources, list):
        return [], [CheckResult("bundle:resources", "fail", "lista bundle.resources ausente")]
    normalized = [str(item) for item in resources]
    return normalized, []


def check_bundle_resources(resources: List[str]) -> List[CheckResult]:
    rows: List[CheckResult] = []
    resource_set = set(resources)
    for entry in CRITICAL_BUNDLE_ENTRIES:
        if entry in resource_set:
            rows.append(CheckResult(f"bundle:{entry}", "ok", "entrada registrada"))
        else:
            rows.append(CheckResult(f"bundle:{entry}", "fail", "entrada ausente em tauri bundle.resources"))

    if "resources/ocr_overlay_audit.py" in resource_set:
        rows.append(CheckResult("bundle:resources/ocr_overlay_audit.py", "ok", "audit script empacotado"))
    else:
        rows.append(
            CheckResult(
                "bundle:resources/ocr_overlay_audit.py",
                "warn",
                "ausente no bundle; validar necessidade em runtime do OCR",
            )
        )
    return rows


def check_pycache_leaks() -> List[CheckResult]:
    pycache_files = sorted(ROOT.glob("app/src-tauri/resources/__pycache__/*.pyc"))
    if not pycache_files:
        return [CheckResult("hygiene:pycache", "ok", "sem artefatos pycache em resources")]
    return [
        CheckResult(
            "hygiene:pycache",
            "warn",
            f"{len(pycache_files)} arquivo(s) pyc em resources; remover do pacote",
        )
    ]


def summarize(results: List[CheckResult], fail_on_warning: bool) -> Tuple[bool, Dict[str, int]]:
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for row in results:
        counts[row.status] = counts.get(row.status, 0) + 1
    has_fail = counts["fail"] > 0
    has_warn = counts["warn"] > 0
    overall_ok = not has_fail and not (fail_on_warning and has_warn)
    return overall_ok, counts


def write_report(path: Path, results: List[CheckResult], counts: Dict[str, int], overall_ok: bool) -> None:
    lines: List[str] = []
    lines.append("# OCR Overlay Pre-Release Sanity Report")
    lines.append("")
    lines.append(f"- generated_at: `{time.strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"- overall_ok: `{int(overall_ok)}`")
    lines.append(f"- ok: `{counts['ok']}`")
    lines.append(f"- warn: `{counts['warn']}`")
    lines.append(f"- fail: `{counts['fail']}`")
    lines.append("")
    lines.append("| check_id | status | detail |")
    lines.append("| --- | --- | --- |")
    for row in results:
        lines.append(f"| {row.check_id} | {row.status} | {row.detail} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir / f"ocr-overlay-prerelease-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[CheckResult] = []
    results.extend(check_required_files())
    results.extend(check_sync_pairs())
    bundle_resources, bundle_load_checks = load_tauri_bundle_resources()
    results.extend(bundle_load_checks)
    if bundle_resources:
        results.extend(check_bundle_resources(bundle_resources))
    results.extend(check_pycache_leaks())

    overall_ok, counts = summarize(results, bool(args.fail_on_warning))
    report_path = out_dir / "report.md"
    manifest_path = out_dir / "report.manifest.json"
    write_report(report_path, results, counts, overall_ok)
    manifest_path.write_text(
        json.dumps(
            {
                "runner": "run_ocr_overlay_prerelease_sanity.py",
                "overall_ok": overall_ok,
                "counts": counts,
                "generated_at_epoch_s": time.time(),
                "artifacts": {"report_md": str(report_path), "manifest": str(manifest_path)},
                "results": [row.__dict__ for row in results],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Wrote: {report_path}")
    print(f"Wrote: {manifest_path}")
    if not overall_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
