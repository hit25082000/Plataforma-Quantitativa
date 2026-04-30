"""M9 — RAG em Tempo Real (fase inicial).

Pipeline local (degradável):
1) Ingestão de eventos do router
2) Agregação em janelas temporais
3) Vetorização leve (sem dependências externas)
4) Busca vetorial para injeção de contexto no chat

Quando configurado, publica também os eventos em Redpanda/Kafka.
Se o broker/lib não estiver disponível, o pipeline de trading continua normal.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from config import (
    RAG_ENABLED,
    RAG_MAX_CONTEXT_CHARS,
    RAG_REDPANDA_BROKERS,
    RAG_REDPANDA_RETENTION_MS,
    RAG_TOPIC_PREFIX,
    RAG_TOP_K,
    RAG_VECTOR_CLOUD_ENABLED,
    RAG_VECTOR_CLOUD_PROVIDER,
    RAG_VECTOR_CLOUD_TIMEOUT_S,
    RAG_VECTOR_TTL_SECONDS,
    RAG_VIEW_LAG_WARN_MS,
    RAG_VIEWS_BACKEND,
    RAG_VIEWS_ENABLED,
    RAG_VIEWS_SQLITE_PATH,
    RAG_WALL_MIN_QTY,
    RAG_WINDOW_SECONDS,
    RAG_PINECONE_API_KEY,
    RAG_PINECONE_INDEX_HOST,
    RAG_PINECONE_NAMESPACE,
    RAG_VECTARA_API_KEY,
    RAG_VECTARA_BASE_URL,
    RAG_VECTARA_CORPUS_KEY,
)

logger = logging.getLogger(__name__)

_VECTOR_DIM = 12


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts_ms(raw: Any) -> int:
    if isinstance(raw, (int, float)):
        v = float(raw)
        if v <= 0:
            return 0
        return int(v if v > 1e12 else v * 1000.0)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return 0
        try:
            v = float(s)
            return int(v if v > 1e12 else v * 1000.0)
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000.0)
        except Exception:
            return 0
    return 0


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        out = float(v)
        if math.isfinite(out):
            return out
    except Exception:
        pass
    return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _event_topic_suffix(msg: dict[str, Any]) -> str:
    topic = str(msg.get("topic") or "")
    typ = str(msg.get("type") or "")
    if topic == "market" and typ == "trade":
        return "trades"
    if topic == "market" and typ == "dom_snapshot":
        return "dom-snapshots"
    if topic == "alert":
        return "alerts"
    return "signals"


def _extract_ticker(msg: dict[str, Any]) -> str:
    for key in ("ticker", "symbol", "asset"):
        val = (msg.get(key) or "").strip() if isinstance(msg.get(key), str) else ""
        if val:
            return val.upper()
    return "GLOBAL"


def _sum_dom_qty(levels: Any) -> float:
    if not isinstance(levels, list):
        return 0.0
    total = 0.0
    for level in levels:
        if isinstance(level, dict):
            total += _safe_float(level.get("qty", level.get("size", level.get("volume", 0))))
            continue
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            total += _safe_float(level[1])
    return total


@dataclass
class VectorRecord:
    record_id: str
    embedding: list[float]
    metadata: dict[str, Any]
    created_ms: int


class InMemoryVectorStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_ms = max(60, int(ttl_seconds)) * 1000
        self._records: list[VectorRecord] = []
        self._lock = threading.Lock()

    def _cleanup_locked(self, now_ms: int) -> int:
        cutoff = now_ms - self._ttl_ms
        before = len(self._records)
        self._records = [r for r in self._records if r.created_ms >= cutoff]
        return before - len(self._records)

    def upsert(self, record: VectorRecord) -> int:
        with self._lock:
            self._records = [r for r in self._records if r.record_id != record.record_id]
            self._records.append(record)
            return self._cleanup_locked(_now_ms())

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int,
        ticker: str | None = None,
        min_score: float = 0.05,
    ) -> list[dict[str, Any]]:
        now = _now_ms()
        with self._lock:
            self._cleanup_locked(now)
            scored: list[dict[str, Any]] = []
            for rec in self._records:
                md_ticker = str(rec.metadata.get("ticker") or "")
                if ticker and md_ticker and md_ticker != ticker:
                    continue
                score = _cosine_similarity(embedding, rec.embedding)
                if score < min_score:
                    continue
                scored.append({"score": score, "metadata": rec.metadata})
            scored.sort(key=lambda x: float(x["score"]), reverse=True)
            return scored[: max(1, top_k)]

    def size(self) -> int:
        with self._lock:
            self._cleanup_locked(_now_ms())
            return len(self._records)


class PineconeVectorStore:
    """Persistência vetorial cloud opcional (REST)."""

    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        index_host: str,
        namespace: str,
        timeout_s: float,
        ttl_seconds: int,
    ) -> None:
        self.enabled = bool(enabled)
        self._api_key = (api_key or "").strip()
        raw_host = (index_host or "").strip().rstrip("/")
        self._namespace = (namespace or "intraday").strip() or "intraday"
        self._timeout_s = max(0.2, float(timeout_s))
        self._ttl_ms = max(60, int(ttl_seconds)) * 1000
        self._init_error = ""
        self._last_error = ""
        self._base_url = ""

        if not self.enabled:
            return
        if not self._api_key:
            self._init_error = "missing_api_key"
            return
        if not raw_host:
            self._init_error = "missing_index_host"
            return
        self._base_url = raw_host if raw_host.startswith(("http://", "https://")) else f"https://{raw_host}"

    @property
    def ready(self) -> bool:
        return self.enabled and not self._init_error and bool(self._base_url)

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict[str, Any]:
        return {
            "provider": "pinecone",
            "enabled": self.enabled,
            "ready": self.ready,
            "namespace": self._namespace,
            "index_host": self._base_url,
            "init_error": self._init_error,
            "last_error": self._last_error,
        }

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.ready:
            return None
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Api-Key": self._api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    return {}
                data = json.loads(raw)
                if isinstance(data, dict):
                    self._last_error = ""
                    return data
                self._last_error = "invalid_json_payload"
                return None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:300]
            self._last_error = f"http_{e.code}:{err_body}"
            return None
        except Exception as e:  # noqa: BLE001
            self._last_error = str(e)
            return None

    def upsert(self, record: VectorRecord) -> bool:
        if not self.ready:
            return False
        payload = {
            "namespace": self._namespace,
            "vectors": [
                {
                    "id": record.record_id,
                    "values": record.embedding,
                    "metadata": {**record.metadata, "created_ms": int(record.created_ms)},
                }
            ],
        }
        return self._request("/vectors/upsert", payload) is not None

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int,
        ticker: str | None = None,
        min_score: float = 0.05,
    ) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        payload: dict[str, Any] = {
            "namespace": self._namespace,
            "vector": embedding,
            "topK": max(1, int(top_k)),
            "includeMetadata": True,
        }
        if ticker:
            payload["filter"] = {"ticker": {"$eq": ticker}}
        data = self._request("/query", payload)
        if data is None:
            return []

        now_ms = _now_ms()
        cutoff = now_ms - self._ttl_ms
        out: list[dict[str, Any]] = []
        for item in data.get("matches") or []:
            if not isinstance(item, dict):
                continue
            score = _safe_float(item.get("score"), 0.0)
            if score < min_score:
                continue
            md = item.get("metadata")
            if not isinstance(md, dict):
                continue
            ref_ms = _parse_ts_ms(md.get("window_end_ms")) or _parse_ts_ms(md.get("created_ms"))
            if ref_ms > 0 and ref_ms < cutoff:
                continue
            out.append({"score": score, "metadata": md})
        out.sort(key=lambda x: float(x["score"]), reverse=True)
        return out[: max(1, top_k)]


class VectaraVectorStore:
    """Persistência vetorial cloud opcional (Vectara API v2)."""

    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        corpus_key: str,
        base_url: str,
        timeout_s: float,
        ttl_seconds: int,
    ) -> None:
        self.enabled = bool(enabled)
        self._api_key = (api_key or "").strip()
        self._corpus_key = (corpus_key or "").strip()
        self._base_url = (base_url or "https://api.vectara.io").strip().rstrip("/")
        self._timeout_s = max(0.2, float(timeout_s))
        self._ttl_ms = max(60, int(ttl_seconds)) * 1000
        self._init_error = ""
        self._last_error = ""
        if not self.enabled:
            return
        if not self._api_key:
            self._init_error = "missing_api_key"
        elif not self._corpus_key:
            self._init_error = "missing_corpus_key"

    @property
    def ready(self) -> bool:
        return self.enabled and not self._init_error

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict[str, Any]:
        return {
            "provider": "vectara",
            "enabled": self.enabled,
            "ready": self.ready,
            "base_url": self._base_url,
            "corpus_key": self._corpus_key,
            "init_error": self._init_error,
            "last_error": self._last_error,
        }

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.ready:
            return None
        req = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw) if raw.strip() else {}
                if isinstance(data, dict):
                    self._last_error = ""
                    return data
                self._last_error = "invalid_json_payload"
                return None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:300]
            self._last_error = f"http_{e.code}:{err_body}"
            return None
        except Exception as e:  # noqa: BLE001
            self._last_error = str(e)
            return None

    def upsert(self, record: VectorRecord) -> bool:
        if not self.ready:
            return False
        doc_text = json.dumps(
            {
                "record_id": record.record_id,
                "metadata": record.metadata,
                "embedding": record.embedding,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        payload = {
            "type": "document",
            "document": {
                "id": record.record_id,
                "type": "core",
                "metadata": {
                    **record.metadata,
                    "created_ms": int(record.created_ms),
                    "ticker": str(record.metadata.get("ticker") or ""),
                },
                "title": f"RAG {record.metadata.get('ticker','GLOBAL')} {record.metadata.get('window_start','')}",
                "text": doc_text,
            },
        }
        out = self._request(f"/v2/corpora/{self._corpus_key}/documents", payload)
        return out is not None

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int,
        ticker: str | None = None,
        min_score: float = 0.05,
    ) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        payload: dict[str, Any] = {
            "query": {
                "type": "text",
                "text": "market context",
            },
            "search": {
                "corpora": [{"corpus_key": self._corpus_key}],
                "limit": max(1, int(top_k)),
            },
            "generation": {"enabled": False},
        }
        out = self._request("/v2/query", payload)
        if out is None:
            return []

        now_ms = _now_ms()
        cutoff = now_ms - self._ttl_ms
        results: list[dict[str, Any]] = []
        for item in out.get("results") or []:
            if not isinstance(item, dict):
                continue
            score = _safe_float(item.get("score"), 0.0)
            if score < min_score:
                continue
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, dict):
                continue
            md_ticker = str(metadata.get("ticker") or "").upper()
            if ticker and md_ticker and md_ticker != ticker.upper():
                continue
            ref_ms = _parse_ts_ms(metadata.get("window_end_ms")) or _parse_ts_ms(metadata.get("created_ms"))
            if ref_ms > 0 and ref_ms < cutoff:
                continue
            results.append({"score": score, "metadata": metadata})

        if results:
            results.sort(key=lambda x: float(x["score"]), reverse=True)
            return results[: max(1, top_k)]

        # fallback compatível: usa payload do documento quando a API não devolve metadata flat
        compat: list[dict[str, Any]] = []
        for item in out.get("results") or []:
            if not isinstance(item, dict):
                continue
            score = _safe_float(item.get("score"), 0.0)
            if score < min_score:
                continue
            text = str(item.get("text") or "")
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            md = parsed.get("metadata")
            if not isinstance(md, dict):
                continue
            md_ticker = str(md.get("ticker") or "").upper()
            if ticker and md_ticker and md_ticker != ticker.upper():
                continue
            ref_ms = _parse_ts_ms(md.get("window_end_ms")) or _parse_ts_ms(md.get("created_ms"))
            if ref_ms > 0 and ref_ms < cutoff:
                continue
            compat.append({"score": score, "metadata": md})
        compat.sort(key=lambda x: float(x["score"]), reverse=True)
        return compat[: max(1, top_k)]


class MaterializedViewsStore:
    """Agregados intraday em memória para consultas rápidas de contexto."""

    def __init__(self, *, enabled: bool, window_seconds: int, lag_warn_ms: int, wall_min_qty: int) -> None:
        self.enabled = bool(enabled)
        self._window_ms = max(30, int(window_seconds)) * 1000
        self._lag_warn_ms = max(250, int(lag_warn_ms))
        self._wall_min_qty = max(1, int(wall_min_qty))
        self._trades: dict[str, deque[tuple[int, float, int, int, int, int]]] = defaultdict(deque)
        self._dom_walls: dict[str, deque[tuple[int, int]]] = defaultdict(deque)
        self._last_update_ms: dict[str, int] = {}
        self._lock = threading.Lock()

    def _prune_locked(self, ticker: str, cutoff_ms: int) -> None:
        t = self._trades.get(ticker)
        if t is not None:
            while t and t[0][0] < cutoff_ms:
                t.popleft()
            if not t:
                self._trades.pop(ticker, None)
        d = self._dom_walls.get(ticker)
        if d is not None:
            while d and d[0][0] < cutoff_ms:
                d.popleft()
            if not d:
                self._dom_walls.pop(ticker, None)

    def _count_walls(self, levels: Any) -> int:
        if not isinstance(levels, list):
            return 0
        count = 0
        for level in levels:
            qty = 0.0
            if isinstance(level, dict):
                qty = _safe_float(level.get("qty", level.get("size", level.get("volume", 0))))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                qty = _safe_float(level[1])
            if qty >= float(self._wall_min_qty):
                count += 1
        return count

    def ingest(self, msg: dict[str, Any]) -> bool:
        if not self.enabled or not isinstance(msg, dict):
            return False
        topic = str(msg.get("topic") or "")
        msg_type = str(msg.get("type") or "")
        if topic != "market":
            return False
        if msg_type not in ("trade", "dom_snapshot"):
            return False

        ticker = _extract_ticker(msg)
        ts_ms = _parse_ts_ms(msg.get("ts")) or _now_ms()
        cutoff = ts_ms - self._window_ms
        with self._lock:
            self._prune_locked(ticker, cutoff)
            if msg_type == "trade":
                qty = max(0, _safe_int(msg.get("qty", 0)))
                price = _safe_float(msg.get("price", 0.0))
                if qty <= 0 or price <= 0:
                    return False
                net_aggr = _safe_int(msg.get("net_aggression", 0))
                buy_agent = max(0, _safe_int(msg.get("buy_agent", 0)))
                sell_agent = max(0, _safe_int(msg.get("sell_agent", 0)))
                self._trades[ticker].append((ts_ms, price, qty, net_aggr, buy_agent, sell_agent))
            else:
                wall_count = self._count_walls(msg.get("buy")) + self._count_walls(msg.get("sell"))
                self._dom_walls[ticker].append((ts_ms, wall_count))
            self._last_update_ms[ticker] = ts_ms
        return True

    def query(self, ticker: str, *, lookback_seconds: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "ticker": ticker or "GLOBAL", "message": "views_disabled"}
        now_ms = _now_ms()
        lookback_ms = self._window_ms if lookback_seconds is None else max(30, int(lookback_seconds)) * 1000
        cutoff = now_ms - lookback_ms
        target = (ticker or "GLOBAL").strip().upper() or "GLOBAL"

        with self._lock:
            tickers = [target] if target != "GLOBAL" else sorted(set(self._trades.keys()) | set(self._dom_walls.keys()))
            all_trades: list[tuple[int, float, int, int, int, int]] = []
            all_walls: list[tuple[int, int]] = []
            last_update = 0
            for tk in tickers:
                self._prune_locked(tk, cutoff)
                all_trades.extend(list(self._trades.get(tk) or ()))
                all_walls.extend(list(self._dom_walls.get(tk) or ()))
                last_update = max(last_update, int(self._last_update_ms.get(tk, 0)))

        trade_count = len(all_trades)
        total_qty = int(sum(t[2] for t in all_trades))
        total_notional = sum(t[1] * t[2] for t in all_trades)
        vwap = (total_notional / total_qty) if total_qty > 0 else 0.0
        aggression_delta = int(sum(t[3] for t in all_trades))
        buyers: dict[int, int] = defaultdict(int)
        sellers: dict[int, int] = defaultdict(int)
        for _, _, qty, _, buy_agent, sell_agent in all_trades:
            if buy_agent > 0:
                buyers[buy_agent] += qty
            if sell_agent > 0:
                sellers[sell_agent] += qty
        top_buyers = [{"agent": a, "qty": q} for a, q in sorted(buyers.items(), key=lambda kv: kv[1], reverse=True)[:5]]
        top_sellers = [{"agent": a, "qty": q} for a, q in sorted(sellers.items(), key=lambda kv: kv[1], reverse=True)[:5]]
        latest_wall_count = all_walls[-1][1] if all_walls else 0
        wall_count_max = max((x[1] for x in all_walls), default=0)
        lag_ms = 0 if last_update <= 0 else max(0, now_ms - last_update)
        has_data = bool(trade_count > 0 or wall_count_max > 0)

        return {
            "enabled": True,
            "ticker": target,
            "lookback_seconds": lookback_ms // 1000,
            "trade_count": trade_count,
            "trade_qty_sum": total_qty,
            "vwap_running": round(vwap, 6) if vwap > 0 else 0.0,
            "aggression_delta": aggression_delta,
            "latest_wall_count": int(latest_wall_count),
            "wall_count_max": int(wall_count_max),
            "top_buyers": top_buyers,
            "top_sellers": top_sellers,
            "lag_ms": int(lag_ms),
            "fresh": bool(lag_ms <= self._lag_warn_ms),
            "has_data": has_data,
            "as_of": _to_iso(now_ms),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            tracked = sorted(set(self._trades.keys()) | set(self._dom_walls.keys()))
        return {
            "enabled": self.enabled,
            "backend": "memory",
            "window_seconds": self._window_ms // 1000,
            "lag_warn_ms": self._lag_warn_ms,
            "wall_min_qty": self._wall_min_qty,
            "tracked_tickers": tracked,
            "tracked_tickers_count": len(tracked),
        }


class SqlMaterializedViewsStore:
    """Agregados intraday em SQL local (SQLite) para facilitar evolução para engine SQL."""

    def __init__(
        self,
        *,
        enabled: bool,
        window_seconds: int,
        lag_warn_ms: int,
        wall_min_qty: int,
        db_path: str,
    ) -> None:
        self.enabled = bool(enabled)
        self._window_ms = max(30, int(window_seconds)) * 1000
        self._lag_warn_ms = max(250, int(lag_warn_ms))
        self._wall_min_qty = max(1, int(wall_min_qty))
        raw_path = (db_path or "").strip()
        self._db_path = raw_path if raw_path else os.path.join("distributor", "logs", "rag_views.sqlite3")
        self._lock = threading.Lock()
        self._init_error = ""
        self._ready = False
        self._prune_interval_ms = 5000
        self._next_prune_ms: dict[str, int] = {}

        if not self.enabled:
            return
        try:
            parent = os.path.dirname(self._db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with closing(self._connect()) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_trades (
                        ts_ms INTEGER NOT NULL,
                        ticker TEXT NOT NULL,
                        price REAL NOT NULL,
                        qty INTEGER NOT NULL,
                        net_aggr INTEGER NOT NULL,
                        buy_agent INTEGER NOT NULL,
                        sell_agent INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_trades_ticker_ts ON rag_trades(ticker, ts_ms)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_dom_walls (
                        ts_ms INTEGER NOT NULL,
                        ticker TEXT NOT NULL,
                        wall_count INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_dom_walls_ticker_ts ON rag_dom_walls(ticker, ts_ms)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_view_updates (
                        ticker TEXT PRIMARY KEY,
                        last_update_ms INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()
            self._ready = True
        except Exception as e:  # noqa: BLE001
            self._init_error = str(e)
            self._ready = False
            logger.warning("RAG views SQL desabilitado (%s)", e)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=1.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.row_factory = sqlite3.Row
        return conn

    def _should_prune_locked(self, ticker: str, ts_ms: int) -> bool:
        next_prune = int(self._next_prune_ms.get(ticker, 0))
        if ts_ms < next_prune:
            return False
        self._next_prune_ms[ticker] = int(ts_ms + self._prune_interval_ms)
        return True

    def _count_walls(self, levels: Any) -> int:
        if not isinstance(levels, list):
            return 0
        count = 0
        for level in levels:
            qty = 0.0
            if isinstance(level, dict):
                qty = _safe_float(level.get("qty", level.get("size", level.get("volume", 0))))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                qty = _safe_float(level[1])
            if qty >= float(self._wall_min_qty):
                count += 1
        return count

    def ingest(self, msg: dict[str, Any]) -> bool:
        if not self.enabled or not self._ready or not isinstance(msg, dict):
            return False
        topic = str(msg.get("topic") or "")
        msg_type = str(msg.get("type") or "")
        if topic != "market":
            return False
        if msg_type not in ("trade", "dom_snapshot"):
            return False

        ticker = _extract_ticker(msg)
        ts_ms = _parse_ts_ms(msg.get("ts")) or _now_ms()
        cutoff = ts_ms - self._window_ms
        try:
            with self._lock, closing(self._connect()) as conn:
                if msg_type == "trade":
                    qty = max(0, _safe_int(msg.get("qty", 0)))
                    price = _safe_float(msg.get("price", 0.0))
                    if qty <= 0 or price <= 0:
                        return False
                    conn.execute(
                        """
                        INSERT INTO rag_trades(ts_ms, ticker, price, qty, net_aggr, buy_agent, sell_agent)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(ts_ms),
                            ticker,
                            float(price),
                            int(qty),
                            int(_safe_int(msg.get("net_aggression", 0))),
                            max(0, int(_safe_int(msg.get("buy_agent", 0)))),
                            max(0, int(_safe_int(msg.get("sell_agent", 0)))),
                        ),
                    )
                else:
                    wall_count = self._count_walls(msg.get("buy")) + self._count_walls(msg.get("sell"))
                    conn.execute(
                        "INSERT INTO rag_dom_walls(ts_ms, ticker, wall_count) VALUES(?, ?, ?)",
                        (int(ts_ms), ticker, int(wall_count)),
                    )
                if self._should_prune_locked(ticker, int(ts_ms)):
                    conn.execute("DELETE FROM rag_trades WHERE ticker = ? AND ts_ms < ?", (ticker, int(cutoff)))
                    conn.execute("DELETE FROM rag_dom_walls WHERE ticker = ? AND ts_ms < ?", (ticker, int(cutoff)))
                conn.execute(
                    """
                    INSERT INTO rag_view_updates(ticker, last_update_ms) VALUES(?, ?)
                    ON CONFLICT(ticker) DO UPDATE SET last_update_ms = excluded.last_update_ms
                    """,
                    (ticker, int(ts_ms)),
                )
                conn.commit()
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("RAG views SQL ingest falhou: %s", e)
            return False

    def query(self, ticker: str, *, lookback_seconds: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "ticker": ticker or "GLOBAL", "message": "views_disabled"}
        if not self._ready:
            return {"enabled": False, "ticker": ticker or "GLOBAL", "message": "views_sql_not_ready"}

        now_ms = _now_ms()
        lookback_ms = self._window_ms if lookback_seconds is None else max(30, int(lookback_seconds)) * 1000
        cutoff = now_ms - lookback_ms
        target = (ticker or "GLOBAL").strip().upper() or "GLOBAL"

        if target == "GLOBAL":
            ticker_predicate = ""
            params: tuple[Any, ...] = (int(cutoff),)
        else:
            ticker_predicate = "AND ticker = ?"
            params = (int(cutoff), target)

        try:
            with self._lock, closing(self._connect()) as conn:
                row = conn.execute(
                    f"""
                    SELECT
                        COUNT(*) AS trade_count,
                        COALESCE(SUM(qty), 0) AS trade_qty_sum,
                        COALESCE(SUM(price * qty), 0.0) AS notional_sum,
                        COALESCE(SUM(net_aggr), 0) AS aggression_delta
                    FROM rag_trades
                    WHERE ts_ms >= ? {ticker_predicate}
                    """,
                    params,
                ).fetchone()
                trade_count = int(row["trade_count"] if row else 0)
                total_qty = int(row["trade_qty_sum"] if row else 0)
                total_notional = float(row["notional_sum"] if row else 0.0)
                aggression_delta = int(row["aggression_delta"] if row else 0)

                latest_wall = conn.execute(
                    f"""
                    SELECT wall_count
                    FROM rag_dom_walls
                    WHERE ts_ms >= ? {ticker_predicate}
                    ORDER BY ts_ms DESC
                    LIMIT 1
                    """,
                    params,
                ).fetchone()
                latest_wall_count = int(latest_wall["wall_count"] if latest_wall else 0)

                wall_max = conn.execute(
                    f"""
                    SELECT COALESCE(MAX(wall_count), 0) AS wall_count_max
                    FROM rag_dom_walls
                    WHERE ts_ms >= ? {ticker_predicate}
                    """,
                    params,
                ).fetchone()
                wall_count_max = int(wall_max["wall_count_max"] if wall_max else 0)

                buyer_rows = conn.execute(
                    f"""
                    SELECT buy_agent AS agent, SUM(qty) AS qty
                    FROM rag_trades
                    WHERE ts_ms >= ? {ticker_predicate} AND buy_agent > 0
                    GROUP BY buy_agent
                    ORDER BY qty DESC
                    LIMIT 5
                    """,
                    params,
                ).fetchall()
                top_buyers = [{"agent": int(r["agent"]), "qty": int(r["qty"])} for r in buyer_rows]

                seller_rows = conn.execute(
                    f"""
                    SELECT sell_agent AS agent, SUM(qty) AS qty
                    FROM rag_trades
                    WHERE ts_ms >= ? {ticker_predicate} AND sell_agent > 0
                    GROUP BY sell_agent
                    ORDER BY qty DESC
                    LIMIT 5
                    """,
                    params,
                ).fetchall()
                top_sellers = [{"agent": int(r["agent"]), "qty": int(r["qty"])} for r in seller_rows]

                lag_row = conn.execute(
                    f"""
                    SELECT MAX(last_update_ms) AS last_update_ms
                    FROM rag_view_updates
                    WHERE 1=1 {ticker_predicate}
                    """,
                    (() if target == "GLOBAL" else (target,)),
                ).fetchone()
                last_update = int(lag_row["last_update_ms"] if lag_row and lag_row["last_update_ms"] else 0)

            vwap = (total_notional / total_qty) if total_qty > 0 else 0.0
            lag_ms = 0 if last_update <= 0 else max(0, now_ms - last_update)
            has_data = bool(trade_count > 0 or wall_count_max > 0)
            return {
                "enabled": True,
                "ticker": target,
                "lookback_seconds": lookback_ms // 1000,
                "trade_count": trade_count,
                "trade_qty_sum": total_qty,
                "vwap_running": round(vwap, 6) if vwap > 0 else 0.0,
                "aggression_delta": aggression_delta,
                "latest_wall_count": int(latest_wall_count),
                "wall_count_max": int(wall_count_max),
                "top_buyers": top_buyers,
                "top_sellers": top_sellers,
                "lag_ms": int(lag_ms),
                "fresh": bool(lag_ms <= self._lag_warn_ms),
                "has_data": has_data,
                "as_of": _to_iso(now_ms),
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("RAG views SQL query falhou: %s", e)
            return {"enabled": False, "ticker": target, "message": "views_sql_query_failed"}

    def status(self) -> dict[str, Any]:
        tracked: list[str] = []
        if self.enabled and self._ready:
            try:
                with self._lock, closing(self._connect()) as conn:
                    rows = conn.execute("SELECT ticker FROM rag_view_updates ORDER BY ticker ASC").fetchall()
                    tracked = [str(r["ticker"]) for r in rows if r["ticker"]]
            except Exception:
                tracked = []
        return {
            "enabled": self.enabled,
            "backend": "sqlite",
            "ready": self._ready,
            "db_path": self._db_path,
            "init_error": self._init_error,
            "window_seconds": self._window_ms // 1000,
            "lag_warn_ms": self._lag_warn_ms,
            "wall_min_qty": self._wall_min_qty,
            "tracked_tickers": tracked,
            "tracked_tickers_count": len(tracked),
        }


class RedpandaStreamPublisher:
    """Publicação best-effort para Redpanda/Kafka."""

    def __init__(self, brokers_csv: str, topic_prefix: str, retention_ms: int) -> None:
        self.enabled = bool((brokers_csv or "").strip())
        self._topic_prefix = (topic_prefix or "pq").strip()
        self._retention_ms = int(retention_ms)
        self._brokers = [b.strip() for b in (brokers_csv or "").split(",") if b.strip()]
        self._producer: Any = None
        self._admin: Any = None
        self._init_error: str = ""
        if not self.enabled:
            return
        try:
            from kafka import KafkaProducer  # type: ignore
            from kafka.admin import KafkaAdminClient, NewTopic  # type: ignore

            self._producer = KafkaProducer(
                bootstrap_servers=self._brokers,
                acks=1,
                linger_ms=1,
                value_serializer=lambda x: json.dumps(x, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
            )
            self._admin = KafkaAdminClient(bootstrap_servers=self._brokers, client_id="pq-rag")
            topics = [
                NewTopic(name=f"{self._topic_prefix}.trades", num_partitions=3, replication_factor=1),
                NewTopic(name=f"{self._topic_prefix}.dom-snapshots", num_partitions=3, replication_factor=1),
                NewTopic(name=f"{self._topic_prefix}.alerts", num_partitions=1, replication_factor=1),
                NewTopic(name=f"{self._topic_prefix}.signals", num_partitions=1, replication_factor=1),
            ]
            try:
                self._admin.create_topics(topics=topics, validate_only=False)
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            self._init_error = str(e)
            self._producer = None
            self._admin = None
            logger.warning("RAG stream: Redpanda/Kafka indisponível (%s)", e)

    @property
    def ready(self) -> bool:
        return self.enabled and self._producer is not None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "topic_prefix": self._topic_prefix,
            "retention_ms": self._retention_ms,
            "brokers": list(self._brokers),
            "init_error": self._init_error,
        }

    def publish(self, topic_suffix: str, payload: dict[str, Any], key: str = "") -> bool:
        if not self.ready:
            return False
        assert self._producer is not None
        topic = f"{self._topic_prefix}.{topic_suffix}"
        try:
            self._producer.send(
                topic,
                payload,
                key=(key.encode("utf-8") if key else None),
            )
            return True
        except Exception:
            return False


@dataclass
class WindowAggregate:
    ticker: str
    window_start_ms: int
    window_end_ms: int
    event_count: int = 0
    trade_count: int = 0
    trade_qty_sum: int = 0
    net_aggression_sum: int = 0
    dom_snapshot_count: int = 0
    dom_buy_qty: float = 0.0
    dom_sell_qty: float = 0.0
    alert_count: int = 0
    signal_green_count: int = 0
    signal_red_count: int = 0
    signal_neutral_count: int = 0
    inversion_count: int = 0
    urgency_sum: float = 0.0
    urgency_samples: int = 0
    price_sum: float = 0.0
    price_samples: int = 0
    last_price: float = 0.0
    last_vwap: float = 0.0
    event_types: set[str] = field(default_factory=set)

    def add_event(self, msg: dict[str, Any]) -> None:
        msg_type = str(msg.get("type") or "")
        topic = str(msg.get("topic") or "")
        self.event_count += 1
        if msg_type:
            self.event_types.add(msg_type)
        if topic == "market" and msg_type == "trade":
            qty = max(0, _safe_int(msg.get("qty", 0)))
            price = _safe_float(msg.get("price", 0))
            self.trade_count += 1
            self.trade_qty_sum += qty
            self.net_aggression_sum += _safe_int(msg.get("net_aggression", 0))
            if price > 0:
                self.last_price = price
                self.price_sum += price
                self.price_samples += 1
            vwap = _safe_float(msg.get("vwap", 0))
            if vwap > 0:
                self.last_vwap = vwap
            return
        if topic == "market" and msg_type == "dom_snapshot":
            self.dom_snapshot_count += 1
            self.dom_buy_qty += _sum_dom_qty(msg.get("buy"))
            self.dom_sell_qty += _sum_dom_qty(msg.get("sell"))
            return
        if topic == "alert":
            self.alert_count += 1
            return
        if msg_type == "flow_inversion":
            self.inversion_count += 1
            return
        if msg_type == "macd_signal":
            direction = str(msg.get("direction") or "")
            if direction == "buy":
                self.signal_green_count += 1
            elif direction == "sell":
                self.signal_red_count += 1
            return
        if topic == "agent007" and msg_type == "state":
            signal = str(msg.get("signal") or "neutral")
            if signal == "green":
                self.signal_green_count += 1
            elif signal == "red":
                self.signal_red_count += 1
            else:
                self.signal_neutral_count += 1
            urg = _safe_float(msg.get("urgency_0_100"), -1.0)
            if urg >= 0:
                self.urgency_sum += urg
                self.urgency_samples += 1

    def to_embedding(self) -> list[float]:
        total_signal = self.signal_green_count + self.signal_red_count + self.signal_neutral_count
        avg_urg = self.urgency_sum / max(1, self.urgency_samples)
        aggression_balance = _clamp(
            math.tanh(self.net_aggression_sum / max(1.0, float(self.trade_qty_sum or 1))),
            -1.0,
            1.0,
        )
        dom_total = self.dom_buy_qty + self.dom_sell_qty
        dom_imbalance = 0.0 if dom_total <= 0 else _clamp((self.dom_buy_qty - self.dom_sell_qty) / dom_total, -1.0, 1.0)
        signal_balance = _clamp((self.signal_green_count - self.signal_red_count) / max(1.0, float(total_signal)), -1.0, 1.0)
        vwap_distance = 0.0
        if self.last_price > 0 and self.last_vwap > 0:
            vwap_distance = _clamp(
                math.tanh((self.last_price - self.last_vwap) / max(1e-9, self.last_vwap * 0.0025)),
                -1.0,
                1.0,
            )
        bullish = _clamp(max(aggression_balance, 0.0) + max(signal_balance, 0.0) * 0.5, 0.0, 1.0)
        bearish = _clamp(max(-aggression_balance, 0.0) + max(-signal_balance, 0.0) * 0.5, 0.0, 1.0)
        return [
            _clamp(math.tanh(self.trade_count / 120.0), 0.0, 1.0),  # 0: intensidade de trades
            _clamp(math.tanh(math.log1p(max(0, self.trade_qty_sum)) / 10.0), 0.0, 1.0),  # 1: volume
            aggression_balance,  # 2: saldo de agressão
            dom_imbalance,  # 3: imbalance DOM
            _clamp(math.tanh(self.alert_count / 8.0), 0.0, 1.0),  # 4: alertas
            signal_balance,  # 5: balanço de sinais
            _clamp(avg_urg / 100.0, 0.0, 1.0),  # 6: urgência
            _clamp(math.tanh(self.inversion_count / 6.0), 0.0, 1.0),  # 7: inversões
            vwap_distance,  # 8: distância VWAP
            _clamp(len(self.event_types) / 6.0, 0.0, 1.0),  # 9: diversidade de eventos
            bullish,  # 10: viés comprador
            bearish,  # 11: viés vendedor
        ]

    def metadata(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "window_start": _to_iso(self.window_start_ms),
            "window_end": _to_iso(self.window_end_ms),
            "event_count": self.event_count,
            "trade_count": self.trade_count,
            "trade_qty_sum": self.trade_qty_sum,
            "net_aggression_sum": self.net_aggression_sum,
            "dom_snapshot_count": self.dom_snapshot_count,
            "dom_buy_qty": round(self.dom_buy_qty, 2),
            "dom_sell_qty": round(self.dom_sell_qty, 2),
            "alert_count": self.alert_count,
            "signal_green_count": self.signal_green_count,
            "signal_red_count": self.signal_red_count,
            "signal_neutral_count": self.signal_neutral_count,
            "inversion_count": self.inversion_count,
            "urgency_avg": round(self.urgency_sum / max(1, self.urgency_samples), 2),
            "last_price": self.last_price,
            "last_vwap": self.last_vwap,
            "event_types": sorted(self.event_types),
        }


def _query_to_embedding(query: str, snapshot: dict[str, Any] | None) -> list[float]:
    q = (query or "").lower()
    vec = [0.0] * _VECTOR_DIM
    vec[9] = 0.2  # baseline de contexto

    def has_any(words: Iterable[str]) -> bool:
        return any(w in q for w in words)

    if has_any(("volume", "lote", "lotes", "negócio", "negocios")):
        vec[0] += 0.7
        vec[1] += 1.0
    if has_any(("agress", "fluxo", "absor", "pression")):
        vec[2] += 0.9
    if has_any(("dom", "livro", "muralha", "parede")):
        vec[3] += 1.0
    if has_any(("alerta", "iceberg", "rompimento", "breakout")):
        vec[4] += 1.0
    if has_any(("sinal", "tendência", "tendencia", "viés", "vies")):
        vec[5] += 0.9
    if has_any(("urgência", "urgencia", "aceler", "forte")):
        vec[6] += 0.9
    if has_any(("invers", "virada", "flip")):
        vec[7] += 1.0
    if has_any(("vwap", "médio", "medio")):
        vec[8] += 1.0
    if has_any(("compr", "alta", "subindo", "bull", "verde")):
        vec[2] += 0.5
        vec[5] += 0.4
        vec[10] += 1.0
    if has_any(("vend", "queda", "caindo", "bear", "vermelho")):
        vec[2] -= 0.5
        vec[5] -= 0.4
        vec[11] += 1.0
    if has_any(("5 min", "5min", "cinco minutos", "janela", "histórico", "historico")):
        vec[9] += 0.8

    if snapshot:
        signal = str(snapshot.get("signal") or "neutral")
        if signal == "green":
            vec[10] += 0.2
        elif signal == "red":
            vec[11] += 0.2

    if sum(abs(v) for v in vec) <= 1e-9:
        vec[0] = 0.3
        vec[1] = 0.3
        vec[2] = 0.3
        vec[9] = 0.8
    return vec


class RealtimeRagEngine:
    def __init__(
        self,
        *,
        enabled: bool,
        window_seconds: int,
        ttl_seconds: int,
        top_k: int,
        max_context_chars: int,
        redpanda_brokers: str,
        topic_prefix: str,
        retention_ms: int,
        vector_cloud_enabled: bool = False,
        vector_cloud_provider: str = "pinecone",
        vector_cloud_timeout_s: float = 1.5,
        pinecone_api_key: str = "",
        pinecone_index_host: str = "",
        pinecone_namespace: str = "intraday",
        vectara_api_key: str = "",
        vectara_corpus_key: str = "",
        vectara_base_url: str = "https://api.vectara.io",
        views_enabled: bool = True,
        views_backend: str = "memory",
        views_sqlite_path: str = "",
        view_lag_warn_ms: int = 1000,
        wall_min_qty: int = 500,
    ) -> None:
        self._enabled = bool(enabled)
        self._window_ms = max(30, int(window_seconds)) * 1000
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._top_k = max(1, int(top_k))
        self._max_context_chars = max(600, int(max_context_chars))
        self._windows: dict[tuple[str, int], WindowAggregate] = {}
        self._store = InMemoryVectorStore(ttl_seconds)
        self._publisher = RedpandaStreamPublisher(redpanda_brokers, topic_prefix, retention_ms)
        selected_views_backend = (views_backend or "memory").strip().lower()
        if selected_views_backend == "sqlite":
            self._views = SqlMaterializedViewsStore(
                enabled=views_enabled,
                window_seconds=window_seconds,
                lag_warn_ms=view_lag_warn_ms,
                wall_min_qty=wall_min_qty,
                db_path=views_sqlite_path,
            )
        else:
            if selected_views_backend not in ("", "memory"):
                logger.warning("RAG views backend inválido '%s'; usando memory.", selected_views_backend)
            self._views = MaterializedViewsStore(
                enabled=views_enabled,
                window_seconds=window_seconds,
                lag_warn_ms=view_lag_warn_ms,
                wall_min_qty=wall_min_qty,
            )
        self._view_lag_warn_ms = max(250, int(view_lag_warn_ms))
        self._last_view_lag_warn_ms = 0
        self._cloud_provider = (vector_cloud_provider or "").strip().lower()
        self._cloud_store: PineconeVectorStore | VectaraVectorStore | None = None
        if vector_cloud_enabled and self._cloud_provider == "pinecone":
            self._cloud_store = PineconeVectorStore(
                enabled=True,
                api_key=pinecone_api_key,
                index_host=pinecone_index_host,
                namespace=pinecone_namespace,
                timeout_s=vector_cloud_timeout_s,
                ttl_seconds=ttl_seconds,
            )
        elif vector_cloud_enabled and self._cloud_provider == "vectara":
            self._cloud_store = VectaraVectorStore(
                enabled=True,
                api_key=vectara_api_key,
                corpus_key=vectara_corpus_key,
                base_url=vectara_base_url,
                timeout_s=vector_cloud_timeout_s,
                ttl_seconds=ttl_seconds,
            )
        self._lock = threading.Lock()
        self._metrics: dict[str, int | float] = {
            "events_ingested_total": 0,
            "events_ignored_total": 0,
            "windows_finalized_total": 0,
            "embeddings_stored_total": 0,
            "vectors_expired_total": 0,
            "vector_queries_total": 0,
            "vector_query_miss_total": 0,
            "context_injections_total": 0,
            "stream_published_total": 0,
            "stream_publish_failures_total": 0,
            "vector_cloud_upsert_total": 0,
            "vector_cloud_upsert_failures_total": 0,
            "vector_cloud_query_total": 0,
            "vector_cloud_query_failures_total": 0,
            "vector_cloud_query_hits_total": 0,
            "views_ingested_total": 0,
            "views_query_total": 0,
            "views_stale_fallback_total": 0,
            "last_query_ms": 0.0,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _flush_closed_windows_locked(self, now_ms: int) -> list[VectorRecord]:
        to_close = [k for k, w in self._windows.items() if w.window_end_ms <= now_ms]
        persisted: list[VectorRecord] = []
        for key in to_close:
            w = self._windows.pop(key)
            if w.event_count <= 0:
                continue
            md = w.metadata()
            md["created_ms"] = now_ms
            record = VectorRecord(
                record_id=f"{w.ticker}:{w.window_start_ms}",
                embedding=w.to_embedding(),
                metadata=md,
                created_ms=now_ms,
            )
            expired = self._store.upsert(record)
            self._metrics["windows_finalized_total"] = int(self._metrics["windows_finalized_total"]) + 1
            self._metrics["embeddings_stored_total"] = int(self._metrics["embeddings_stored_total"]) + 1
            self._metrics["vectors_expired_total"] = int(self._metrics["vectors_expired_total"]) + int(expired)
            persisted.append(record)
        return persisted

    def _mirror_records_to_cloud(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        if self._cloud_store is None or not self._cloud_store.ready:
            return
        for record in records:
            self._metrics["vector_cloud_upsert_total"] = int(self._metrics["vector_cloud_upsert_total"]) + 1
            ok = self._cloud_store.upsert(record)
            if not ok:
                self._metrics["vector_cloud_upsert_failures_total"] = int(
                    self._metrics["vector_cloud_upsert_failures_total"]
                ) + 1

    def _query_cloud_store(self, embedding: list[float], *, ticker: str | None, top_k: int) -> list[dict[str, Any]]:
        if self._cloud_store is None or not self._cloud_store.ready:
            return []
        self._metrics["vector_cloud_query_total"] = int(self._metrics["vector_cloud_query_total"]) + 1
        results = self._cloud_store.query(embedding, top_k=top_k, ticker=ticker)
        if not results and self._cloud_store.last_error:
            self._metrics["vector_cloud_query_failures_total"] = int(
                self._metrics["vector_cloud_query_failures_total"]
            ) + 1
        if not results:
            return []
        self._metrics["vector_cloud_query_hits_total"] = int(self._metrics["vector_cloud_query_hits_total"]) + len(results)
        return results

    def _build_view_summary(self, ticker: str) -> str:
        view = self.materialized_view(ticker=ticker)
        if not view.get("enabled"):
            return ""
        if not bool(view.get("has_data")):
            return ""
        self._metrics["views_query_total"] = int(self._metrics["views_query_total"]) + 1
        lag_ms = int(view.get("lag_ms", 0))
        if lag_ms > self._view_lag_warn_ms:
            self._metrics["views_stale_fallback_total"] = int(self._metrics["views_stale_fallback_total"]) + 1
            now = _now_ms()
            if now - self._last_view_lag_warn_ms > 5000:
                logger.warning(
                    "RAG views stale lag=%sms ticker=%s; fallback to vector-only context",
                    lag_ms,
                    ticker or "GLOBAL",
                )
                self._last_view_lag_warn_ms = now
            return ""
        buyers = view.get("top_buyers") or []
        sellers = view.get("top_sellers") or []
        top_buyer = buyers[0] if isinstance(buyers, list) and buyers else None
        top_seller = sellers[0] if isinstance(sellers, list) and sellers else None
        return (
            "Views materializadas intraday: "
            f"VWAP={view.get('vwap_running', 0)} "
            f"aggr={view.get('aggression_delta', 0)} "
            f"walls(atual/max)={view.get('latest_wall_count', 0)}/{view.get('wall_count_max', 0)} "
            f"top_buy={top_buyer.get('agent') if isinstance(top_buyer, dict) else '-'}:"
            f"{top_buyer.get('qty') if isinstance(top_buyer, dict) else 0} "
            f"top_sell={top_seller.get('agent') if isinstance(top_seller, dict) else '-'}:"
            f"{top_seller.get('qty') if isinstance(top_seller, dict) else 0}"
        )

    def ingest(self, msg: dict[str, Any]) -> None:
        if not self._enabled:
            return
        if not isinstance(msg, dict):
            self._metrics["events_ignored_total"] = int(self._metrics["events_ignored_total"]) + 1
            return
        topic = str(msg.get("topic") or "")
        if topic not in ("market", "alert", "agent007"):
            self._metrics["events_ignored_total"] = int(self._metrics["events_ignored_total"]) + 1
            return

        ts_ms = _parse_ts_ms(msg.get("ts")) or _now_ms()
        ticker = _extract_ticker(msg)
        window_start = (ts_ms // self._window_ms) * self._window_ms
        key = (ticker, window_start)
        flushed: list[VectorRecord]
        with self._lock:
            flushed = self._flush_closed_windows_locked(ts_ms)
            agg = self._windows.get(key)
            if agg is None:
                agg = WindowAggregate(
                    ticker=ticker,
                    window_start_ms=window_start,
                    window_end_ms=window_start + self._window_ms,
                )
                self._windows[key] = agg
            agg.add_event(msg)
            self._metrics["events_ingested_total"] = int(self._metrics["events_ingested_total"]) + 1
        self._mirror_records_to_cloud(flushed)

        if self._views.ingest(msg):
            self._metrics["views_ingested_total"] = int(self._metrics["views_ingested_total"]) + 1

        suffix = _event_topic_suffix(msg)
        if self._publisher.enabled:
            ok = self._publisher.publish(suffix, msg, key=ticker)
            if ok:
                self._metrics["stream_published_total"] = int(self._metrics["stream_published_total"]) + 1
            else:
                self._metrics["stream_publish_failures_total"] = int(
                    self._metrics["stream_publish_failures_total"]
                ) + 1

    def build_context_for_query(
        self,
        query: str,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._enabled:
            return {"enabled": False, "context": "", "results": []}

        t0 = time.perf_counter()
        ticker = _extract_ticker(snapshot or {})
        qvec = _query_to_embedding(query, snapshot)
        flushed: list[VectorRecord]
        with self._lock:
            flushed = self._flush_closed_windows_locked(_now_ms())
            local_results = self._store.query(qvec, top_k=self._top_k, ticker=ticker if ticker != "GLOBAL" else None)
            if not local_results and ticker != "GLOBAL":
                local_results = self._store.query(qvec, top_k=self._top_k, ticker=None)
        self._mirror_records_to_cloud(flushed)

        results = local_results
        source = "local"
        if not results:
            cloud_results = self._query_cloud_store(
                qvec,
                ticker=(ticker if ticker != "GLOBAL" else None),
                top_k=self._top_k,
            )
            if not cloud_results and ticker != "GLOBAL":
                cloud_results = self._query_cloud_store(qvec, ticker=None, top_k=self._top_k)
            if cloud_results:
                results = cloud_results
                source = "cloud"
        self._metrics["vector_queries_total"] = int(self._metrics["vector_queries_total"]) + 1
        if not results:
            self._metrics["vector_query_miss_total"] = int(self._metrics["vector_query_miss_total"]) + 1
            self._metrics["last_query_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            return {"enabled": True, "context": "", "results": []}

        lines = ["Contexto RAG intraday (janelas recentes):"]
        view_summary = self._build_view_summary(ticker)
        if view_summary:
            lines.append(view_summary)
        for idx, hit in enumerate(results, start=1):
            md = hit["metadata"]
            score = float(hit["score"])
            lines.append(
                f"{idx}. {md.get('ticker','?')} [{md.get('window_start')} - {md.get('window_end')}] "
                f"score={score:.3f} trades={md.get('trade_count',0)} vol={md.get('trade_qty_sum',0)} "
                f"aggr={md.get('net_aggression_sum',0)} sinal(g/r)={md.get('signal_green_count',0)}/{md.get('signal_red_count',0)} "
                f"alerts={md.get('alert_count',0)}"
            )
        lines.append(f"Fonte vetorial: {source}")
        context = "\n".join(lines)
        if len(context) > self._max_context_chars:
            context = context[: self._max_context_chars].rstrip() + "..."
        self._metrics["context_injections_total"] = int(self._metrics["context_injections_total"]) + 1
        self._metrics["last_query_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        return {"enabled": True, "context": context, "results": results}

    def metrics(self) -> dict[str, Any]:
        flushed: list[VectorRecord]
        with self._lock:
            flushed = self._flush_closed_windows_locked(_now_ms())
            data = dict(self._metrics)
            data["active_windows"] = len(self._windows)
            data["vector_store_size"] = self._store.size()
            data["window_seconds"] = self._window_ms // 1000
            data["ttl_seconds"] = self._ttl_seconds
            data["top_k"] = self._top_k
            data["max_context_chars"] = self._max_context_chars
            data["stream"] = self._publisher.status()
            data["vector_cloud"] = (
                self._cloud_store.status()
                if self._cloud_store is not None
                else {"provider": self._cloud_provider or "none", "enabled": False, "ready": False}
            )
            data["views"] = self._views.status()
        self._mirror_records_to_cloud(flushed)
        return data

    def materialized_view(self, *, ticker: str, lookback_seconds: int | None = None) -> dict[str, Any]:
        if not self._enabled:
            return {"enabled": False, "ticker": (ticker or "GLOBAL"), "message": "rag_disabled"}
        return self._views.query(ticker, lookback_seconds=lookback_seconds)

    def status(self) -> dict[str, Any]:
        return {"enabled": self._enabled, "metrics": self.metrics()}


def create_rag_engine_from_config() -> RealtimeRagEngine | None:
    if not RAG_ENABLED:
        return None
    return RealtimeRagEngine(
        enabled=True,
        window_seconds=RAG_WINDOW_SECONDS,
        ttl_seconds=RAG_VECTOR_TTL_SECONDS,
        top_k=RAG_TOP_K,
        max_context_chars=RAG_MAX_CONTEXT_CHARS,
        redpanda_brokers=RAG_REDPANDA_BROKERS,
        topic_prefix=RAG_TOPIC_PREFIX,
        retention_ms=RAG_REDPANDA_RETENTION_MS,
        vector_cloud_enabled=RAG_VECTOR_CLOUD_ENABLED,
        vector_cloud_provider=RAG_VECTOR_CLOUD_PROVIDER,
        vector_cloud_timeout_s=RAG_VECTOR_CLOUD_TIMEOUT_S,
        pinecone_api_key=RAG_PINECONE_API_KEY,
        pinecone_index_host=RAG_PINECONE_INDEX_HOST,
        pinecone_namespace=RAG_PINECONE_NAMESPACE,
        vectara_api_key=RAG_VECTARA_API_KEY,
        vectara_corpus_key=RAG_VECTARA_CORPUS_KEY,
        vectara_base_url=RAG_VECTARA_BASE_URL,
        views_enabled=RAG_VIEWS_ENABLED,
        views_backend=RAG_VIEWS_BACKEND,
        views_sqlite_path=RAG_VIEWS_SQLITE_PATH,
        view_lag_warn_ms=RAG_VIEW_LAG_WARN_MS,
        wall_min_qty=RAG_WALL_MIN_QTY,
    )
