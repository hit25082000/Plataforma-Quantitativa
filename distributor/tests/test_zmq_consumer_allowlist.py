"""Testes de allowlist de egress para ZmqConsumer."""

from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Garante que o diretório do distributor está no path (para import direto)
_DIST_DIR = Path(__file__).resolve().parent.parent
if str(_DIST_DIR) not in sys.path:
    sys.path.insert(0, str(_DIST_DIR))

from zmq_consumer import ZmqConsumer


class TestZmqConsumerAllowlistInit(unittest.TestCase):
    """Testa inicialização do ZmqConsumer com/sem allowlist."""

    def _make_queue(self) -> asyncio.Queue:
        return asyncio.Queue(maxsize=100)

    def test_no_allowlist_by_default(self) -> None:
        import os
        # Garante que ZMQ_ALLOWED_IPS não está no ambiente
        env_backup = os.environ.pop("ZMQ_ALLOWED_IPS", None)
        try:
            c = ZmqConsumer("tcp://127.0.0.1:5555", self._make_queue())
            self.assertIsNone(c._allowed_ips_raw)
        finally:
            if env_backup is not None:
                os.environ["ZMQ_ALLOWED_IPS"] = env_backup

    def test_explicit_allowed_ips_raw(self) -> None:
        c = ZmqConsumer(
            "tcp://127.0.0.1:5555",
            self._make_queue(),
            allowed_ips_raw="127.0.0.1/32",
        )
        self.assertEqual(c._allowed_ips_raw, "127.0.0.1/32")

    def test_reads_from_env_var(self) -> None:
        import os
        os.environ["ZMQ_ALLOWED_IPS"] = "192.168.0.0/24"
        try:
            c = ZmqConsumer("tcp://127.0.0.1:5555", self._make_queue())
            self.assertEqual(c._allowed_ips_raw, "192.168.0.0/24")
        finally:
            del os.environ["ZMQ_ALLOWED_IPS"]

    def test_explicit_param_overrides_env(self) -> None:
        import os
        os.environ["ZMQ_ALLOWED_IPS"] = "10.0.0.0/8"
        try:
            c = ZmqConsumer(
                "tcp://127.0.0.1:5555",
                self._make_queue(),
                allowed_ips_raw="127.0.0.1/32",
            )
            self.assertEqual(c._allowed_ips_raw, "127.0.0.1/32")
        finally:
            del os.environ["ZMQ_ALLOWED_IPS"]


class TestZmqConsumerCheckEgressAllowlist(unittest.TestCase):
    """Testa _check_egress_allowlist() com mocks do enforce."""

    def _make_consumer(self, allowed_ips_raw=None) -> ZmqConsumer:
        return ZmqConsumer(
            "tcp://127.0.0.1:5555",
            asyncio.Queue(maxsize=10),
            allowed_ips_raw=allowed_ips_raw,
        )

    def test_no_allowlist_always_passes(self) -> None:
        c = self._make_consumer(None)
        # Sem allowlist, sempre retorna True
        self.assertTrue(c._check_egress_allowlist())

    def test_blocked_by_allowlist_returns_false(self) -> None:
        c = self._make_consumer("1.2.3.4/32")  # IP que não resolve para 127.0.0.1
        with patch(
            "zmq_consumer.enforce_endpoint_ip_allowlist",
            side_effect=RuntimeError("ZMQ_ALLOWED_IPS bloqueou endpoint ZMQ: host=127.0.0.1"),
        ):
            result = c._check_egress_allowlist()
        self.assertFalse(result)

    def test_allowed_allowlist_returns_true(self) -> None:
        c = self._make_consumer("127.0.0.1/32")
        with patch(
            "zmq_consumer.enforce_endpoint_ip_allowlist",
            return_value={"enabled": True, "endpoint_host": "127.0.0.1", "resolved_ips": ["127.0.0.1"], "allowed_ips": ["127.0.0.1/32"]},
        ):
            result = c._check_egress_allowlist()
        self.assertTrue(result)

    def test_address_without_scheme_normalized(self) -> None:
        """Endereço sem '://' deve ser normalizado antes de passar para urlparse."""
        c = self._make_consumer("127.0.0.0/8")
        c._address = "127.0.0.1:5555"  # sem tcp://
        captured_url = {}

        def _mock_enforce(*, endpoint_url, raw_allowlist, env_var_name, endpoint_label):
            captured_url["url"] = endpoint_url
            return {"enabled": True, "endpoint_host": "127.0.0.1", "resolved_ips": [], "allowed_ips": []}

        with patch("zmq_consumer.enforce_endpoint_ip_allowlist", side_effect=_mock_enforce):
            c._check_egress_allowlist()

        self.assertIn("://", captured_url.get("url", ""))

    def test_has_egress_allowlist_false_skips_check(self) -> None:
        """Se _HAS_EGRESS_ALLOWLIST=False (import falhou), retorna True sem chamar nada."""
        import zmq_consumer as mod
        c = self._make_consumer("1.2.3.4/32")
        original = mod._HAS_EGRESS_ALLOWLIST
        try:
            mod._HAS_EGRESS_ALLOWLIST = False
            result = c._check_egress_allowlist()
        finally:
            mod._HAS_EGRESS_ALLOWLIST = original
        self.assertTrue(result)


class TestZmqConsumerRunBlockedByAllowlist(unittest.TestCase):
    """Testa que _run() não chega ao ZMQ.Context quando bloqueado."""

    def test_run_aborts_when_allowlist_blocks(self) -> None:
        c = ZmqConsumer(
            "tcp://127.0.0.1:5555",
            asyncio.Queue(maxsize=10),
            allowed_ips_raw="1.2.3.4/32",
        )

        zmq_context_called = {"called": False}

        def _mock_context(*args, **kwargs):
            zmq_context_called["called"] = True
            return MagicMock()

        with patch("zmq_consumer.enforce_endpoint_ip_allowlist", side_effect=RuntimeError("blocked")):
            with patch("zmq.Context", side_effect=_mock_context):
                c._run()

        # ZMQ.Context NÃO deve ter sido chamado (conexão foi abortada antes)
        self.assertFalse(zmq_context_called["called"])

    def test_run_proceeds_without_allowlist(self) -> None:
        """Sem allowlist, _run() chega ao ZMQ.Context (mas podemos mock o socket)."""
        c = ZmqConsumer(
            "tcp://127.0.0.1:9999",  # porta inválida — só testa que chegou no ZMQ
            asyncio.Queue(maxsize=10),
            allowed_ips_raw=None,
        )

        ctx_mock = MagicMock()
        sock_mock = MagicMock()
        sock_mock.recv_string.side_effect = Exception("stop")
        ctx_mock.socket.return_value = sock_mock

        zmq_context_called = {"called": False}

        def _mock_context(*args, **kwargs):
            zmq_context_called["called"] = True
            c._stop_event.set()  # Encerra o loop imediatamente após conectar/criar o contexto
            return ctx_mock

        with patch("zmq.Context", side_effect=_mock_context):
            c._run()

        self.assertTrue(zmq_context_called["called"])


if __name__ == "__main__":
    unittest.main()
