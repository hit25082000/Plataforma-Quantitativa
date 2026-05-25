from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class SessionOpsStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    component TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    build TEXT,
                    asset TEXT,
                    monitor_dpi TEXT,
                    last_error_code TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    error_code TEXT,
                    metrics_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts_utc);
                CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, ts_utc);
                CREATE TABLE IF NOT EXISTS incidents (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_session_ts ON incidents(session_id, ts_utc);
                CREATE TABLE IF NOT EXISTS gates (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    session_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(session_id, key)
                );
                """
            )

    def upsert_event(self, event: dict[str, Any]) -> None:
        now = time.time()
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            return
        session_id = str(event.get("session_id") or "").strip()
        if not session_id:
            return
        run_id = str(event.get("run_id") or "")
        component = str(event.get("component") or "")
        status = str(event.get("status") or "unknown")
        ts_utc = str(event.get("ts_utc") or "")
        error_code = str(event.get("error_code") or "")
        metrics_json = json.dumps(event.get("metrics") or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        artifacts_json = json.dumps(event.get("artifacts") or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        payload_json = json.dumps(event.get("payload") or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        raw_json = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO events(event_id, session_id, event_type, stage, status, ts_utc, error_code, metrics_json, artifacts_json, payload_json, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    str(event.get("event_type") or ""),
                    str(event.get("stage") or "runtime"),
                    status,
                    ts_utc,
                    error_code,
                    metrics_json,
                    artifacts_json,
                    payload_json,
                    raw_json,
                ),
            )
            conn.execute(
                """
                INSERT INTO sessions(session_id, run_id, component, status, started_at, build, asset, monitor_dpi, last_error_code, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    last_error_code=excluded.last_error_code,
                    ended_at=CASE WHEN excluded.status IN ('ended','failed','closed') THEN excluded.started_at ELSE sessions.ended_at END
                """,
                (
                    session_id,
                    run_id,
                    component,
                    status,
                    ts_utc,
                    str(event.get("build") or ""),
                    str(event.get("asset") or ""),
                    str(event.get("monitor_dpi") or ""),
                    error_code,
                    now,
                ),
            )

            if str(event.get("event_type") or "") == "incident":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO incidents(event_id, session_id, ts_utc, error_code, status, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, session_id, ts_utc, error_code, status, payload_json),
                )
            if str(event.get("event_type") or "") == "gate_result":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO gates(event_id, session_id, ts_utc, status, error_code, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, session_id, ts_utc, status, error_code, payload_json),
                )

            for key, value in (event.get("artifacts") or {}).items():
                conn.execute(
                    """
                    INSERT INTO artifacts(session_id, key, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (session_id, str(key), str(value), now),
                )

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str, limit_events: int = 200) -> dict[str, Any] | None:
        sid = (session_id or "").strip()
        if not sid:
            return None
        with self._connect() as conn:
            session_row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (sid,)).fetchone()
            if session_row is None:
                return None
            events = conn.execute(
                "SELECT raw_json FROM events WHERE session_id=? ORDER BY ts_utc DESC LIMIT ?",
                (sid, max(1, min(int(limit_events), 2000))),
            ).fetchall()
            artifacts = conn.execute(
                "SELECT key, value, updated_at FROM artifacts WHERE session_id=? ORDER BY updated_at DESC",
                (sid,),
            ).fetchall()
        out = dict(session_row)
        out["events"] = [json.loads(r["raw_json"]) for r in events]
        out["artifacts"] = [dict(r) for r in artifacts]
        return out

    def list_incidents(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY ts_utc DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            row = dict(r)
            row["payload"] = json.loads(row.pop("payload_json", "{}"))
            out.append(row)
        return out

    def timeline(self, limit: int = 300) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT raw_json FROM events ORDER BY ts_utc DESC LIMIT ?",
                (max(1, min(int(limit), 2000)),),
            ).fetchall()
        return [json.loads(r["raw_json"]) for r in rows]
