"""Testes unitários do pipeline RAG em tempo real (M9)."""

from __future__ import annotations

import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _make_config_stub(**overrides: object) -> types.ModuleType:
    cfg = types.ModuleType("config")
    cfg.RAG_ENABLED = overrides.get("RAG_ENABLED", True)
    cfg.RAG_WINDOW_SECONDS = overrides.get("RAG_WINDOW_SECONDS", 300)
    cfg.RAG_VECTOR_TTL_SECONDS = overrides.get("RAG_VECTOR_TTL_SECONDS", 28800)
    cfg.RAG_TOP_K = overrides.get("RAG_TOP_K", 5)
    cfg.RAG_MAX_CONTEXT_CHARS = overrides.get("RAG_MAX_CONTEXT_CHARS", 3200)
    cfg.RAG_REDPANDA_BROKERS = overrides.get("RAG_REDPANDA_BROKERS", "")
    cfg.RAG_TOPIC_PREFIX = overrides.get("RAG_TOPIC_PREFIX", "pq")
    cfg.RAG_REDPANDA_RETENTION_MS = overrides.get("RAG_REDPANDA_RETENTION_MS", 28800000)
    cfg.RAG_VECTOR_CLOUD_ENABLED = overrides.get("RAG_VECTOR_CLOUD_ENABLED", False)
    cfg.RAG_VECTOR_CLOUD_PROVIDER = overrides.get("RAG_VECTOR_CLOUD_PROVIDER", "pinecone")
    cfg.RAG_VECTOR_CLOUD_TIMEOUT_S = overrides.get("RAG_VECTOR_CLOUD_TIMEOUT_S", 1.5)
    cfg.RAG_PINECONE_API_KEY = overrides.get("RAG_PINECONE_API_KEY", "")
    cfg.RAG_PINECONE_INDEX_HOST = overrides.get("RAG_PINECONE_INDEX_HOST", "")
    cfg.RAG_PINECONE_NAMESPACE = overrides.get("RAG_PINECONE_NAMESPACE", "intraday")
    cfg.RAG_VECTARA_API_KEY = overrides.get("RAG_VECTARA_API_KEY", "")
    cfg.RAG_VECTARA_CORPUS_KEY = overrides.get("RAG_VECTARA_CORPUS_KEY", "")
    cfg.RAG_VECTARA_BASE_URL = overrides.get("RAG_VECTARA_BASE_URL", "https://api.vectara.io")
    cfg.RAG_VIEWS_ENABLED = overrides.get("RAG_VIEWS_ENABLED", True)
    cfg.RAG_VIEWS_BACKEND = overrides.get("RAG_VIEWS_BACKEND", "memory")
    cfg.RAG_VIEWS_SQLITE_PATH = overrides.get("RAG_VIEWS_SQLITE_PATH", "")
    cfg.RAG_VIEW_LAG_WARN_MS = overrides.get("RAG_VIEW_LAG_WARN_MS", 1000)
    cfg.RAG_WALL_MIN_QTY = overrides.get("RAG_WALL_MIN_QTY", 500)
    return cfg


class TestRealtimeRag(unittest.TestCase):
    def setUp(self) -> None:
        sys.modules.pop("realtime_rag", None)

    def tearDown(self) -> None:
        sys.modules.pop("realtime_rag", None)
        sys.modules.pop("config", None)

    def _load_module(self, **cfg_overrides: object):
        sys.modules["config"] = _make_config_stub(**cfg_overrides)
        sys.modules.pop("realtime_rag", None)
        import realtime_rag as rr
        return rr

    def test_factory_returns_none_when_disabled(self) -> None:
        rr = self._load_module(RAG_ENABLED=False)
        self.assertIsNone(rr.create_rag_engine_from_config())

    def test_ingest_and_query_returns_context(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        eng = rr.RealtimeRagEngine(
            enabled=True,
            window_seconds=300,
            ttl_seconds=3600,
            top_k=3,
            max_context_chars=2000,
            redpanda_brokers="",
            topic_prefix="pq",
            retention_ms=28800000,
        )
        base = int(time.time() * 1000) - 700_000
        eng.ingest(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "WINFUT",
                "price": 130010.0,
                "qty": 12,
                "net_aggression": 120,
                "vwap": 130000.0,
                "ts": base,
            }
        )
        eng.ingest(
            {
                "topic": "agent007",
                "type": "state",
                "ticker": "WINFUT",
                "signal": "green",
                "urgency_0_100": 72,
                "ts": base + 1000,
            }
        )
        ctx = eng.build_context_for_query(
            "teve agressão compradora nos últimos 5 min?",
            {"ticker": "WINFUT", "signal": "green"},
        )
        self.assertTrue(ctx["enabled"])
        self.assertTrue(ctx["context"])
        self.assertGreaterEqual(len(ctx["results"]), 1)

    def test_query_filters_by_ticker_when_possible(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        eng = rr.RealtimeRagEngine(
            enabled=True,
            window_seconds=300,
            ttl_seconds=3600,
            top_k=5,
            max_context_chars=2000,
            redpanda_brokers="",
            topic_prefix="pq",
            retention_ms=28800000,
        )
        base = int(time.time() * 1000) - 800_000
        eng.ingest(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "WINFUT",
                "price": 130100.0,
                "qty": 20,
                "net_aggression": 250,
                "ts": base,
            }
        )
        eng.ingest(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "WDOFUT",
                "price": 5150.0,
                "qty": 20,
                "net_aggression": -250,
                "ts": base,
            }
        )
        ctx = eng.build_context_for_query(
            "como está o fluxo comprador?",
            {"ticker": "WINFUT", "signal": "green"},
        )
        self.assertGreaterEqual(len(ctx["results"]), 1)
        for item in ctx["results"]:
            self.assertEqual(item["metadata"]["ticker"], "WINFUT")

    def test_stream_metrics_degrade_gracefully_without_broker(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        eng = rr.RealtimeRagEngine(
            enabled=True,
            window_seconds=300,
            ttl_seconds=3600,
            top_k=3,
            max_context_chars=2000,
            redpanda_brokers="127.0.0.1:9092",
            topic_prefix="pq",
            retention_ms=28800000,
        )
        eng.ingest(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "WINFUT",
                "price": 130000.0,
                "qty": 1,
                "net_aggression": 1,
                "ts": int(time.time() * 1000),
            }
        )
        m = eng.metrics()
        self.assertIn("stream", m)
        self.assertTrue(m["stream"]["enabled"])
        published = int(m["stream_published_total"])
        failed = int(m["stream_publish_failures_total"])
        self.assertGreaterEqual(published + failed, 1)

    def test_materialized_view_returns_intraday_aggregates(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        eng = rr.RealtimeRagEngine(
            enabled=True,
            window_seconds=300,
            ttl_seconds=3600,
            top_k=3,
            max_context_chars=2000,
            redpanda_brokers="",
            topic_prefix="pq",
            retention_ms=28800000,
        )
        now_ms = int(time.time() * 1000)
        eng.ingest(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "WINFUT",
                "price": 130000.0,
                "qty": 10,
                "net_aggression": 40,
                "buy_agent": 101,
                "sell_agent": 202,
                "ts": now_ms - 1500,
            }
        )
        eng.ingest(
            {
                "topic": "market",
                "type": "trade",
                "ticker": "WINFUT",
                "price": 130010.0,
                "qty": 20,
                "net_aggression": 60,
                "buy_agent": 101,
                "sell_agent": 303,
                "ts": now_ms - 900,
            }
        )
        eng.ingest(
            {
                "topic": "market",
                "type": "dom_snapshot",
                "ticker": "WINFUT",
                "buy": [{"price": 129995.0, "qty": 600}],
                "sell": [{"price": 130015.0, "qty": 800}],
                "ts": now_ms - 500,
            }
        )

        view = eng.materialized_view(ticker="WINFUT", lookback_seconds=300)
        self.assertTrue(view["enabled"])
        self.assertEqual(view["trade_count"], 2)
        self.assertEqual(view["trade_qty_sum"], 30)
        self.assertAlmostEqual(float(view["vwap_running"]), 130006.666667, places=3)
        self.assertEqual(view["aggression_delta"], 100)
        self.assertGreaterEqual(int(view["latest_wall_count"]), 2)
        self.assertTrue(view["top_buyers"])

    def test_query_falls_back_to_cloud_when_local_store_is_empty(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        eng = rr.RealtimeRagEngine(
            enabled=True,
            window_seconds=300,
            ttl_seconds=3600,
            top_k=3,
            max_context_chars=2000,
            redpanda_brokers="",
            topic_prefix="pq",
            retention_ms=28800000,
        )

        class _FakeCloudStore:
            ready = True
            last_error = ""

            def query(
                self,
                embedding: list[float],
                *,
                top_k: int,
                ticker: str | None = None,
                min_score: float = 0.05,
            ) -> list[dict[str, object]]:
                _ = (embedding, top_k, min_score)
                tk = ticker or "WINFUT"
                return [
                    {
                        "score": 0.91,
                        "metadata": {
                            "ticker": tk,
                            "window_start": "2026-04-23T10:00:00Z",
                            "window_end": "2026-04-23T10:05:00Z",
                            "trade_count": 25,
                            "trade_qty_sum": 900,
                            "net_aggression_sum": 180,
                            "signal_green_count": 3,
                            "signal_red_count": 1,
                            "alert_count": 1,
                        },
                    }
                ]

            def upsert(self, record: object) -> bool:
                _ = record
                return True

            def status(self) -> dict[str, object]:
                return {"provider": "fake", "enabled": True, "ready": True}

        eng._cloud_store = _FakeCloudStore()  # type: ignore[attr-defined]
        ctx = eng.build_context_for_query("como estava o fluxo comprador?", {"ticker": "WINFUT"})
        self.assertTrue(ctx["context"])
        self.assertIn("Fonte vetorial: cloud", ctx["context"])
        self.assertEqual(len(ctx["results"]), 1)
        m = eng.metrics()
        self.assertGreaterEqual(int(m["vector_cloud_query_total"]), 1)

    def test_vectara_provider_initializes_and_reports_status(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        eng = rr.RealtimeRagEngine(
            enabled=True,
            window_seconds=300,
            ttl_seconds=3600,
            top_k=3,
            max_context_chars=2000,
            redpanda_brokers="",
            topic_prefix="pq",
            retention_ms=28800000,
            vector_cloud_enabled=True,
            vector_cloud_provider="vectara",
            vectara_api_key="dummy",
            vectara_corpus_key="corp-us-test",
            vectara_base_url="https://api.vectara.io",
        )
        m = eng.metrics()
        cloud = m["vector_cloud"]
        self.assertEqual(cloud["provider"], "vectara")
        self.assertTrue(cloud["enabled"])
        self.assertTrue(cloud["ready"])

    def test_sqlite_materialized_views_backend(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "rag_views.sqlite3")
            eng = rr.RealtimeRagEngine(
                enabled=True,
                window_seconds=300,
                ttl_seconds=3600,
                top_k=3,
                max_context_chars=2000,
                redpanda_brokers="",
                topic_prefix="pq",
                retention_ms=28800000,
                views_enabled=True,
                views_backend="sqlite",
                views_sqlite_path=sqlite_path,
            )
            now_ms = int(time.time() * 1000)
            eng.ingest(
                {
                    "topic": "market",
                    "type": "trade",
                    "ticker": "WINFUT",
                    "price": 130000.0,
                    "qty": 30,
                    "net_aggression": 90,
                    "buy_agent": 101,
                    "sell_agent": 404,
                    "ts": now_ms - 800,
                }
            )
            eng.ingest(
                {
                    "topic": "market",
                    "type": "dom_snapshot",
                    "ticker": "WINFUT",
                    "buy": [{"price": 129995.0, "qty": 700}],
                    "sell": [{"price": 130010.0, "qty": 520}],
                    "ts": now_ms - 200,
                }
            )
            view = eng.materialized_view(ticker="WINFUT", lookback_seconds=300)
            self.assertTrue(view["enabled"])
            self.assertEqual(view["trade_count"], 1)
            self.assertEqual(view["trade_qty_sum"], 30)
            self.assertEqual(view["aggression_delta"], 90)
            self.assertGreaterEqual(int(view["latest_wall_count"]), 2)
            status = eng.metrics()["views"]
            self.assertEqual(status["backend"], "sqlite")
            self.assertTrue(status["ready"])

    def test_sqlite_materialized_views_persist_across_engine_restart(self) -> None:
        rr = self._load_module(RAG_ENABLED=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "rag_views.sqlite3")
            now_ms = int(time.time() * 1000)

            eng_a = rr.RealtimeRagEngine(
                enabled=True,
                window_seconds=300,
                ttl_seconds=3600,
                top_k=3,
                max_context_chars=2000,
                redpanda_brokers="",
                topic_prefix="pq",
                retention_ms=28800000,
                views_enabled=True,
                views_backend="sqlite",
                views_sqlite_path=sqlite_path,
            )
            eng_a.ingest(
                {
                    "topic": "market",
                    "type": "trade",
                    "ticker": "WINFUT",
                    "price": 130005.0,
                    "qty": 40,
                    "net_aggression": 70,
                    "buy_agent": 777,
                    "sell_agent": 888,
                    "ts": now_ms - 400,
                }
            )
            first_view = eng_a.materialized_view(ticker="WINFUT", lookback_seconds=300)
            self.assertEqual(first_view["trade_count"], 1)

            eng_b = rr.RealtimeRagEngine(
                enabled=True,
                window_seconds=300,
                ttl_seconds=3600,
                top_k=3,
                max_context_chars=2000,
                redpanda_brokers="",
                topic_prefix="pq",
                retention_ms=28800000,
                views_enabled=True,
                views_backend="sqlite",
                views_sqlite_path=sqlite_path,
            )
            second_view = eng_b.materialized_view(ticker="WINFUT", lookback_seconds=300)
            self.assertTrue(second_view["enabled"])
            self.assertEqual(second_view["trade_count"], 1)
            self.assertEqual(second_view["trade_qty_sum"], 40)
            self.assertEqual(second_view["aggression_delta"], 70)
            self.assertTrue(second_view["top_buyers"])


if __name__ == "__main__":
    unittest.main()
