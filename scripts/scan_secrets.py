#!/usr/bin/env python3
"""Scaneia segredos em arquivos staged para bloquear commit acidental."""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    excerpt: str


_OPENAI_KEY_RE = re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}\b")
_AWS_ACCESS_KEY_ID_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_AWS_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\bAWS_SECRET_ACCESS_KEY\b\s*[:=]\s*([\"']?)([A-Za-z0-9/+_=]{40})\1"
)
_SENSITIVE_ASSIGN_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)\b\s*[:=]\s*([\"']?)([^\"'\s#]{8,})\2"
)

_ALLOW_INLINE_MARKER = "allow-secret"

_PLACEHOLDER_SNIPPETS = (
    "changeme",
    "replace_me",
    "replace-this",
    "your_",
    "your-",
    "example",
    "sample",
    "dummy",
    "placeholder",
    "xxxx",
    "*****",
    "<redacted>",
    "<secret>",
    "<token>",
)


def _run_git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _staged_paths() -> List[str]:
    proc = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMRT"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff --cached falhou")
    paths = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return paths


def _read_staged_blob(path: str) -> str | None:
    proc = _run_git(["show", f":{path}"])
    if proc.returncode != 0:
        return None
    if "\x00" in proc.stdout:
        return None
    return proc.stdout


def _read_file_text(path: str) -> str | None:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if "\x00" in data:
        return None
    return data


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    entropy = 0.0
    length = float(len(value))
    for count in counts.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def _looks_placeholder(raw: str) -> bool:
    value = raw.strip().strip("\"'").lower()
    if not value:
        return True
    if value in {"...", "***", "null", "none", "false", "true"}:
        return True
    if value.startswith("${") and value.endswith("}"):
        return True
    if value.startswith("%") and value.endswith("%"):
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    return any(part in value for part in _PLACEHOLDER_SNIPPETS)


def _is_high_entropy_secret(value: str) -> bool:
    if len(value) < 20:
        return False
    has_alpha = any(ch.isalpha() for ch in value)
    has_digit = any(ch.isdigit() for ch in value)
    entropy = _shannon_entropy(value)
    return has_alpha and has_digit and entropy >= 3.2


def scan_text(path: str, text: str) -> List[Finding]:
    findings: List[Finding] = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if _ALLOW_INLINE_MARKER in line.lower():
            continue

        for match in _OPENAI_KEY_RE.finditer(line):
            findings.append(
                Finding(path, idx, "openai_api_key", line[max(0, match.start() - 12) : match.end() + 8].strip())
            )
        for match in _AWS_ACCESS_KEY_ID_RE.finditer(line):
            findings.append(
                Finding(path, idx, "aws_access_key_id", line[max(0, match.start() - 12) : match.end() + 8].strip())
            )

        aws_secret = _AWS_SECRET_ASSIGN_RE.search(line)
        if aws_secret and not _looks_placeholder(aws_secret.group(2)):
            findings.append(Finding(path, idx, "aws_secret_access_key", line))

        generic = _SENSITIVE_ASSIGN_RE.search(line)
        if generic:
            key_name = generic.group(1).upper()
            value = generic.group(3)
            if _looks_placeholder(value):
                continue
            if "PASSWORD" in key_name and len(value) >= 8:
                findings.append(Finding(path, idx, "password_assignment", line))
                continue
            if _is_high_entropy_secret(value):
                findings.append(Finding(path, idx, "high_entropy_secret_assignment", line))

    unique = {}
    for item in findings:
        unique[(item.file, item.line, item.rule, item.excerpt)] = item
    return sorted(unique.values(), key=lambda x: (x.file, x.line, x.rule, x.excerpt))


def scan_paths(paths: Iterable[str], staged: bool) -> List[Finding]:
    findings: List[Finding] = []
    for path in paths:
        content = _read_staged_blob(path) if staged else _read_file_text(path)
        if content is None:
            continue
        findings.extend(scan_text(path, content))
    return findings


def _print_findings(findings: Sequence[Finding]) -> None:
    print("Secret scan encontrou potenciais credenciais sensíveis:")
    for item in findings:
        print(f"  - {item.file}:{item.line} [{item.rule}] {item.excerpt}")
    print(
        "Commit bloqueado. Mova segredos para AWS KMS/gerenciador de segredos e use placeholders em texto plano."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", help="Escaneia somente arquivos staged (default).")
    parser.add_argument("--all-files", action="store_true", help="Escaneia arquivos no working tree.")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="Lista explícita de paths para escanear. Se omitido, usa staged/all-files.",
    )
    args = parser.parse_args()

    if args.staged and args.all_files:
        print("Use apenas um modo: --staged ou --all-files.", file=sys.stderr)
        return 2

    staged_mode = True
    if args.all_files:
        staged_mode = False
    elif args.staged:
        staged_mode = True

    if args.paths:
        paths = [str(Path(p)) for p in args.paths]
    elif staged_mode:
        try:
            paths = _staged_paths()
        except RuntimeError as exc:
            print(f"Erro no git: {exc}", file=sys.stderr)
            return 2
    else:
        proc = _run_git(["ls-files"])
        if proc.returncode != 0:
            print(proc.stderr.strip() or "git ls-files falhou", file=sys.stderr)
            return 2
        paths = [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    if not paths:
        print("Secret scan: nenhum arquivo para verificar.")
        return 0

    findings = scan_paths(paths, staged=staged_mode and not args.paths)
    if findings:
        _print_findings(findings)
        return 1

    print(f"Secret scan OK ({len(paths)} arquivo(s) verificado(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
