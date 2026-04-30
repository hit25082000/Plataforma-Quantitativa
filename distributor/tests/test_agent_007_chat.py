"""Tests for Agent007 chat transport hardening and metrics."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import agent_007_chat as chat


class _JsonResponseCtx:
    def __init__(self, payload: dict[str, object]) -> None:
        self._stream = io.StringIO(json.dumps(payload))

    def __enter__(self) -> io.StringIO:
        return self._stream

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        self._stream.close()
        return False


class TestAgent007Chat(unittest.TestCase):
    def setUp(self) -> None:
        chat.reset_chat_metrics()

    def test_allowlist_blocks_disallowed_endpoint(self) -> None:
        with mock.patch.object(chat, "AGENT007_API_KEY", "sk-test"), mock.patch.object(
            chat, "AGENT007_ALLOWED_IPS", "10.0.0.0/8"
        ), mock.patch("egress_allowlist.resolve_endpoint_ips", return_value=["52.95.1.2"]), mock.patch(
            "agent_007_chat.urllib.request.urlopen"
        ) as mock_urlopen:
            ok, text = chat.run_agent007_chat(
                [{"role": "user", "content": "oi"}],
                {"ticker": "WINFUT"},
            )

        self.assertFalse(ok)
        self.assertIn("allowlist", text.lower())
        mock_urlopen.assert_not_called()
        metrics = chat.chat_metrics()
        self.assertEqual(metrics["requests_total"], 1)
        self.assertEqual(metrics["allowlist_blocked"], 1)
        self.assertEqual(metrics["errors_total"], 1)

    def test_success_writes_audit_without_leaking_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "agent007_audit.jsonl"
            payload = {"choices": [{"message": {"content": "Resposta curta"}}]}
            with mock.patch.object(chat, "AGENT007_API_KEY", "sk-secret-value"), mock.patch.object(
                chat, "AGENT007_ALLOWED_IPS", "52.95.0.0/16"
            ), mock.patch.object(chat, "AGENT007_AUDIT_LOG_PATH", str(audit_path)), mock.patch(
                "egress_allowlist.resolve_endpoint_ips", return_value=["52.95.1.2"]
            ), mock.patch(
                "agent_007_chat.urllib.request.urlopen", return_value=_JsonResponseCtx(payload)
            ):
                ok, text = chat.run_agent007_chat(
                    [{"role": "user", "content": "status?"}],
                    {"ticker": "WINFUT", "last_price": 100.0},
                )

            self.assertTrue(ok)
            self.assertEqual(text, "Resposta curta")
            data = audit_path.read_text(encoding="utf-8")
            self.assertNotIn("sk-secret-value", data)
            records = [json.loads(line) for line in data.splitlines() if line.strip()]
            self.assertTrue(any(r.get("status") == "ok" for r in records))
            metrics = chat.chat_metrics()
            self.assertEqual(metrics["requests_total"], 1)
            self.assertEqual(metrics["success_total"], 1)
            self.assertEqual(metrics["errors_total"], 0)

    def test_rate_limit_counter(self) -> None:
        with mock.patch.object(chat, "AGENT007_CHAT_MIN_INTERVAL_MS", 10_000):
            ok1, _ = chat.check_rate_limit("client-1")
            ok2, _ = chat.check_rate_limit("client-1")

        self.assertTrue(ok1)
        self.assertFalse(ok2)
        metrics = chat.chat_metrics()
        self.assertEqual(metrics["rate_limited"], 1)

    def test_rag_context_is_sent_as_system_message(self) -> None:
        payload = {"choices": [{"message": {"content": "ok"}}]}
        captured_request_body: dict[str, object] = {}

        def _capture_urlopen(req, timeout=0):  # noqa: ANN001
            del timeout
            data = req.data.decode("utf-8") if isinstance(req.data, (bytes, bytearray)) else "{}"
            captured_request_body.update(json.loads(data))
            return _JsonResponseCtx(payload)

        with mock.patch.object(chat, "AGENT007_API_KEY", "sk-test"), mock.patch.object(
            chat, "AGENT007_ALLOWED_IPS", "52.95.0.0/16"
        ), mock.patch(
            "egress_allowlist.resolve_endpoint_ips", return_value=["52.95.1.2"]
        ), mock.patch(
            "agent_007_chat.urllib.request.urlopen", side_effect=_capture_urlopen
        ):
            ok, _ = chat.run_agent007_chat(
                [{"role": "user", "content": "resuma o mercado"}],
                {"ticker": "WINFUT", "last_price": 130000.0},
                rag_context="Contexto RAG intraday: janela com forte agressão compradora.",
            )

        self.assertTrue(ok)
        msgs = captured_request_body.get("messages", [])
        self.assertTrue(any("Contexto intraday recuperado por RAG" in str(m.get("content", "")) for m in msgs))


if __name__ == "__main__":
    unittest.main()
