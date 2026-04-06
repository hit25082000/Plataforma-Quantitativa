#!/usr/bin/env python3
"""
Monitoramento do pipeline: consulta GET /health do distributor e, opcionalmente,
acompanha um ficheiro de log (stdout redirecionado) realçando linhas de métricas.

Uso:
  python scripts/monitor_pipeline.py
  python scripts/monitor_pipeline.py --interval 2
  python scripts/monitor_pipeline.py --log distributor-run.log

Variáveis de ambiente:
  MONITOR_HEALTH_URL  (default http://127.0.0.1:8000/health)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = os.environ.get(
    "MONITOR_HEALTH_URL", "http://127.0.0.1:8000/health"
)

LOG_MARKERS = (
    "Pipeline health:",
    "Router metrics:",
    "Consume loop backlog",
    "Market queue",
    "Market queue full",
    "preemptively dropped",
    "rescued ",
    "[ZmqPublisher]",
    "ZmqPublisher",
)


def _fmt_health(data: dict) -> str:
    parts: list[str] = [
        f"clients={data.get('clients')}",
        f"zmq={data.get('zmq')}",
    ]
    if "zmq_sync" in data:
        parts.append(f"zmq_sync={data.get('zmq_sync')}")
    if "backlog" in data:
        parts.append(f"backlog={data['backlog']}")
        qmax = data.get("queue_maxsize")
        if isinstance(qmax, int) and qmax > 0:
            pct = 100.0 * float(data["backlog"]) / float(qmax)
            parts.append(f"backlog_pct={pct:.1f}%")
    if "route_avg_ms" in data:
        parts.append(f"route_avg_ms={float(data['route_avg_ms']):.4f}")
    if "route_total" in data:
        parts.append(f"route_total={data['route_total']}")
    if "throttled_dom" in data:
        parts.append(f"throttled_dom={data['throttled_dom']}")
    if "dropped_dom_total" in data:
        parts.append(f"dropped_dom={data['dropped_dom_total']}")
    if "rescued_trade_like_total" in data:
        parts.append(f"rescued_trade={data['rescued_trade_like_total']}")
    warn: list[str] = []
    b = data.get("backlog")
    qmax = data.get("queue_maxsize")
    if isinstance(b, int) and isinstance(qmax, int) and qmax > 0:
        if b >= qmax:
            warn.append("FILA_NO_TETO")
        elif b >= int(qmax * 0.7):
            warn.append("FILA_ALTA")
    if warn:
        parts.append("[" + ",".join(warn) + "]")
    return " ".join(parts)


def poll_health(url: str, interval: float, lock: threading.Lock) -> None:
    while True:
        ts = time.strftime("%H:%M:%S")
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            line = _fmt_health(data)
            with lock:
                print(f"[HEALTH {ts}] {line}", flush=True)
        except urllib.error.HTTPError as e:
            with lock:
                print(f"[HEALTH {ts}] HTTP {e.code} {e.reason}", flush=True)
        except urllib.error.URLError as e:
            with lock:
                print(f"[HEALTH {ts}] URL {e.reason}", flush=True)
        except Exception as e:
            with lock:
                print(f"[HEALTH {ts}] ERRO {e}", flush=True)
        time.sleep(interval)


def tail_log(path: Path, lock: threading.Lock) -> None:
    if not path.is_file():
        with lock:
            print(f"[LOG] ficheiro ainda não existe: {path}", flush=True)
    while not path.is_file():
        time.sleep(0.5)
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                if any(m in line for m in LOG_MARKERS):
                    with lock:
                        print(f"[LOG] {line.rstrip()}", flush=True)
            else:
                time.sleep(0.15)


def main() -> int:
    p = argparse.ArgumentParser(description="Monitor distributor /health (+ log opcional).")
    p.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="URL do healthcheck (default: env MONITOR_HEALTH_URL ou localhost:8000)",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Segundos entre polls (default: 5)",
    )
    p.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Ficheiro de log para seguir (ex.: saída do distributor redirecionada)",
    )
    args = p.parse_args()
    if args.interval <= 0:
        print("--interval deve ser > 0", file=sys.stderr)
        return 2

    lock = threading.Lock()
    threads: list[threading.Thread] = []
    if args.log is not None:
        t = threading.Thread(
            target=tail_log, args=(args.log, lock), daemon=True, name="log-tail"
        )
        t.start()
        threads.append(t)

    try:
        poll_health(args.url, args.interval, lock)
    except KeyboardInterrupt:
        with lock:
            print("\n[monitor] interrompido.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
