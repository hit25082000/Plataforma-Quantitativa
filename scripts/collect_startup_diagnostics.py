#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

CANONICAL_PORTS = [8000, 5555, 5556, 5557, 5558]
ENDPOINTS = [
    ("/health", "health"),
    ("/ready", "ready"),
    ("/debug/status", "debug_status"),
    ("/ipc-state", "ipc_state"),
]
LAYER_CHOICES = {
    "port_conflict",
    "engine_not_started",
    "profit_login_market",
    "subscribe_failed",
    "distributor_bootstrap",
    "ipc_fallback",
    "feed_stale",
    "websocket_broadcast",
    "frontend_state",
    "unknown",
}


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def _powershell(script: str, timeout: float = 12.0) -> tuple[int, str, str]:
    return _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


def _safe_json_parse(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _collect_git_snapshot() -> dict[str, Any]:
    branch_rc, branch_out, branch_err = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status_rc, status_out, status_err = _run(["git", "status", "--short"])
    return {
        "branch": (branch_out.strip() if branch_rc == 0 else None),
        "status_lines": [line.rstrip() for line in status_out.splitlines() if line.strip()],
        "errors": [e for e in [branch_err.strip(), status_err.strip()] if e],
    }


def _collect_target_processes() -> list[dict[str, Any]]:
    ps_script = (
        "$all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "  $n = ($_.Name | ForEach-Object { $_.ToLowerInvariant() }); "
        "  ($n -eq 'engine.exe') -or "
        "  ($n -eq 'distributor.exe') -or "
        "  ($n -eq 'profit_ocr_service.exe') -or "
        "  ($n -eq 'python.exe') "
        "} | "
        "Select-Object ProcessId,Name,CommandLine,ExecutablePath | ConvertTo-Json -Compress"
    )
    rc, out, err = _powershell(ps_script, timeout=20.0)
    if rc != 0:
        return [{"error": f"process_query_failed: {err.strip() or 'unknown'}"}]
    parsed = _safe_json_parse(out)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        parsed = []
    result: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "pid": int(item.get("ProcessId") or 0),
                "name": str(item.get("Name") or ""),
                "command_line": str(item.get("CommandLine") or ""),
                "path": str(item.get("ExecutablePath") or ""),
            }
        )
    if result:
        return result

    # Fallback when CIM query is blocked/empty: tasklist per target name.
    fallback: list[dict[str, Any]] = []
    for image_name in ("engine.exe", "python.exe", "distributor.exe", "profit_ocr_service.exe"):
        rc, out, _ = _run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"], timeout=6.0)
        if rc != 0:
            continue
        for raw_line in out.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("INFO:") or line.startswith("INFORMA"):
                continue
            try:
                fields = next(csv.reader([line]))
            except Exception:  # noqa: BLE001
                continue
            if len(fields) < 2:
                continue
            try:
                pid = int(fields[1])
            except ValueError:
                continue
            fallback.append(
                {
                    "pid": pid,
                    "name": fields[0],
                    "command_line": "",
                    "path": "",
                }
            )
    return fallback


def _pid_to_process_name(pid: int) -> str | None:
    if pid <= 0:
        return None
    rc, out, _ = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=5.0)
    if rc != 0:
        return None
    line = out.strip().splitlines()
    if not line:
        return None
    row = line[0].strip()
    if not row or row.startswith("INFO:"):
        return None
    try:
        fields = next(csv.reader([row]))
    except Exception:  # noqa: BLE001
        return None
    return fields[0] if fields else None


def _collect_ports() -> dict[str, Any]:
    rc, out, err = _run(["netstat", "-ano"], timeout=10.0)
    listeners: dict[str, Any] = {}
    if rc != 0:
        for port in CANONICAL_PORTS:
            listeners[str(port)] = {"listening": False, "listeners": [], "error": err.strip() or "netstat_failed"}
        return listeners

    lines = out.splitlines()
    for port in CANONICAL_PORTS:
        entries: list[dict[str, Any]] = []
        port_re = re.compile(rf"^\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$", re.IGNORECASE)
        for line in lines:
            match = port_re.match(line.strip())
            if not match:
                continue
            pid = int(match.group(1))
            pname = _pid_to_process_name(pid)
            entries.append({"pid": pid, "process_name": pname, "raw": line.strip()})
        listeners[str(port)] = {
            "listening": len(entries) > 0,
            "listeners": entries,
        }
    return listeners


def _candidate_log_dirs(repo_root: Path) -> list[Path]:
    dirs: list[Path] = []
    dirs.extend(
        [
            repo_root,
            repo_root / "distributor" / "logs",
            repo_root / "app" / "src-tauri" / "resources",
            repo_root / "app" / "src-tauri" / "target" / "debug" / "resources",
            repo_root / "engine" / "build",
            repo_root / "engine" / "build" / "Release",
            repo_root / "engine" / "build" / "Debug",
        ]
    )
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        dirs.append(Path(local_app_data) / "Plataforma Quantitativa" / "logs")
    app_data = os.environ.get("APPDATA")
    if app_data:
        dirs.append(Path(app_data) / "Plataforma Quantitativa" / "logs")
    return [p for p in dirs if p.exists() and p.is_dir()]


def _read_log_tail(path: Path, max_lines: int = 120) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return lines
    return lines[-max_lines:]


def _collect_logs(repo_root: Path, out_dir: Path) -> dict[str, Any]:
    expected = [
        "runtime-bootstrap.log",
        "profit_engine.log",
        "engine_stderr.log",
        "distributor_stdout.log",
        "distributor_stderr.log",
    ]
    result: dict[str, Any] = {}
    log_dirs = _candidate_log_dirs(repo_root)
    logs_out_dir = out_dir / "logs"
    logs_out_dir.mkdir(parents=True, exist_ok=True)

    for filename in expected:
        candidates: list[Path] = []
        for d in log_dirs:
            p = d / filename
            if p.exists() and p.is_file():
                candidates.append(p)
        if not candidates:
            result[filename] = {"exists": False, "path": None, "size_bytes": 0, "mtime": None}
            continue
        chosen = max(candidates, key=lambda p: p.stat().st_mtime)
        stat = chosen.stat()
        tail = _read_log_tail(chosen)
        copy_path = logs_out_dir / filename
        try:
            copy_path.write_text("\n".join(tail), encoding="utf-8")
        except Exception:  # noqa: BLE001
            copy_path = Path("")
        result[filename] = {
            "exists": True,
            "path": str(chosen),
            "size_bytes": stat.st_size,
            "mtime": dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "tail_file": str(copy_path) if str(copy_path) else None,
        }
    return result


def _fetch_json(base_url: str, path: str, timeout_sec: float = 5.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    req = urlrequest.Request(url, method="GET")
    started = time.monotonic()
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
            parsed = _safe_json_parse(raw)
            if not isinstance(parsed, dict):
                parsed = {"raw": raw}
            return {
                "ok": True,
                "url": url,
                "status_code": int(resp.status),
                "elapsed_ms": elapsed_ms,
                "payload": parsed,
            }
    except urlerror.HTTPError as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        parsed = _safe_json_parse(body)
        return {
            "ok": False,
            "url": url,
            "status_code": int(exc.code),
            "elapsed_ms": elapsed_ms,
            "payload": parsed if isinstance(parsed, dict) else {"raw": body},
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "payload": None,
            "error": str(exc),
        }


def _parse_iso_any(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt_value = dt.datetime.fromisoformat(text)
        return dt_value.timestamp()
    except Exception:  # noqa: BLE001
        return None


def _expected_process_for_port(port: int) -> tuple[str, ...]:
    if port == 8000:
        return ("python.exe", "distributor.exe")
    if port in (5555, 5556):
        return ("engine.exe",)
    if port == 5557:
        return ("python.exe",)
    if port == 5558:
        return ("python.exe", "profit_ocr_service.exe")
    return ()


def _classify(
    *,
    ports: dict[str, Any],
    processes: list[dict[str, Any]],
    health: dict[str, Any],
    ready: dict[str, Any],
    debug_status_1: dict[str, Any],
    debug_status_2: dict[str, Any],
) -> tuple[bool, str, str, str, list[str]]:
    errors: list[str] = []

    for port in CANONICAL_PORTS:
        pkey = str(port)
        listeners = ports.get(pkey, {}).get("listeners", [])
        if not listeners:
            continue
        expected = _expected_process_for_port(port)
        for item in listeners:
            pname = str(item.get("process_name") or "").lower()
            if expected and pname not in expected:
                pid = item.get("pid")
                msg = f"port {port} ocupado por processo inesperado pid={pid} name={pname or 'unknown'}"
                errors.append(msg)
                return (
                    False,
                    msg,
                    "port_conflict",
                    f"Finalizar PID {pid} ({pname or 'unknown'}) e reiniciar startup.",
                    errors,
                )

    if not health.get("ok", False):
        return (
            False,
            "Distributor HTTP indisponível (/health não responde).",
            "distributor_bootstrap",
            "Verificar processo na porta 8000 e logs runtime-bootstrap/distributor stderr.",
            errors,
        )

    ready_payload = ready.get("payload") if isinstance(ready.get("payload"), dict) else {}
    debug_payload_1 = debug_status_1.get("payload") if isinstance(debug_status_1.get("payload"), dict) else {}
    debug_payload_2 = debug_status_2.get("payload") if isinstance(debug_status_2.get("payload"), dict) else {}

    ready_flag = bool(ready_payload.get("ready") is True)
    if not ready_flag:
        ipc_status = str(ready_payload.get("ipc_status") or "")
        if "fallback" in ipc_status.lower():
            return (
                False,
                f"Distributor pronto=false com fallback ({ipc_status}).",
                "ipc_fallback",
                "Inspecionar bootstrap IPC e fallback SHM->ZMQ nos logs.",
                errors,
            )
        return (
            False,
            f"Distributor pronto=false (ipc_status={ipc_status or 'unknown'}).",
            "distributor_bootstrap",
            "Verificar tasks de bootstrap/consumer e erro em /ready.",
            errors,
        )

    feed_live = bool(
        (ready_payload.get("feed_live") is True)
        or (debug_payload_2.get("feed_live") is True)
        or (debug_payload_1.get("feed_live") is True)
    )
    if not feed_live:
        has_engine_process = any(str(p.get("name", "")).lower() == "engine.exe" for p in processes)
        has_5556_listener = bool(ports.get("5556", {}).get("listening"))
        if not has_engine_process and not has_5556_listener:
            return (
                False,
                "Feed sem eventos e engine não encontrado em processo/porta 5556.",
                "engine_not_started",
                "Subir engine e validar login/mercado no profit_engine.log.",
                errors,
            )
        return (
            False,
            "Pipeline pronto, porém feed_live=false sem evento recente.",
            "feed_stale",
            "Validar login/mercado/subscrição e chegada de eventos na engine.",
            errors,
        )

    ws_clients = int(debug_payload_2.get("ws_clients") or 0)
    recv_1 = int(debug_payload_1.get("messages_received_total") or 0)
    recv_2 = int(debug_payload_2.get("messages_received_total") or 0)
    sent_1 = int(debug_payload_1.get("messages_sent_total") or 0)
    sent_2 = int(debug_payload_2.get("messages_sent_total") or 0)
    recv_delta = max(0, recv_2 - recv_1)
    sent_delta = max(0, sent_2 - sent_1)
    if ws_clients > 0 and recv_delta > 0 and sent_delta == 0:
        return (
            False,
            "Eventos recebidos, mas broadcast WS sem envio no intervalo de amostra.",
            "websocket_broadcast",
            "Inspecionar broadcast_queue_depth e filas por cliente.",
            errors,
        )

    return (
        True,
        "Startup/health/readiness coerentes na amostra.",
        "unknown",
        "Sem ação imediata.",
        errors,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coleta diagnóstico de startup/distributor/engine.")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Diretório de saída para artefatos de diagnóstico.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL do distributor.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    git_snapshot = _collect_git_snapshot()
    processes = _collect_target_processes()
    ports = _collect_ports()
    logs = _collect_logs(repo_root, out_dir)

    health = _fetch_json(args.base_url, "/health")
    ready = _fetch_json(args.base_url, "/ready")
    debug_status_1 = _fetch_json(args.base_url, "/debug/status")
    time.sleep(1.2)
    debug_status_2 = _fetch_json(args.base_url, "/debug/status")
    ipc_state = _fetch_json(args.base_url, "/ipc-state")

    ok, root_symptom, likely_layer, next_action, errors = _classify(
        ports=ports,
        processes=processes,
        health=health,
        ready=ready,
        debug_status_1=debug_status_1,
        debug_status_2=debug_status_2,
    )
    if likely_layer not in LAYER_CHOICES:
        likely_layer = "unknown"

    summary = {
        "ok": bool(ok),
        "root_symptom": root_symptom,
        "likely_layer": likely_layer,
        "next_action": next_action,
        "ports": ports,
        "processes": processes,
        "health": health,
        "ready": ready,
        "debug_status": debug_status_2,
        "errors": errors,
    }

    meta = {
        "ts_utc": _now_utc_iso(),
        "hostname": socket.gethostname(),
        "cwd": str(Path.cwd()),
        "repo_root": str(repo_root),
        "base_url": args.base_url,
        "git": git_snapshot,
    }

    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "raw_endpoints.json").write_text(
        json.dumps(
            {
                "health": health,
                "ready": ready,
                "debug_status_1": debug_status_1,
                "debug_status_2": debug_status_2,
                "ipc_state": ipc_state,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"diagnostics_written={out_dir}")
    print(f"ok={summary['ok']} likely_layer={summary['likely_layer']} root_symptom={summary['root_symptom']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
