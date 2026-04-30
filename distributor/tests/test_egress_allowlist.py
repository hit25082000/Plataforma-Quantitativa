"""Tests for shared outbound endpoint IP allowlist helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import egress_allowlist as egress


class TestEgressAllowlist(unittest.TestCase):
    def test_disabled_when_allowlist_empty(self) -> None:
        result = egress.enforce_endpoint_ip_allowlist(
            endpoint_url="https://example.com/v1/chat/completions",
            raw_allowlist="",
            env_var_name="TEST_ALLOWED_IPS",
            endpoint_label="de teste",
        )
        self.assertEqual(result["enabled"], False)
        self.assertEqual(result["endpoint_host"], "")
        self.assertEqual(result["resolved_ips"], [])
        self.assertEqual(result["allowed_ips"], [])

    def test_allows_matching_ip(self) -> None:
        with mock.patch.object(egress, "resolve_endpoint_ips", return_value=["52.95.1.2"]):
            result = egress.enforce_endpoint_ip_allowlist(
                endpoint_url="https://openrouter.ai/api/v1/chat/completions",
                raw_allowlist="52.95.0.0/16",
                env_var_name="TEST_ALLOWED_IPS",
                endpoint_label="de teste",
            )
        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["endpoint_host"], "openrouter.ai")
        self.assertEqual(result["resolved_ips"], ["52.95.1.2"])
        self.assertEqual(result["allowed_ips"], ["52.95.0.0/16"])

    def test_blocks_disallowed_ip(self) -> None:
        with mock.patch.object(egress, "resolve_endpoint_ips", return_value=["8.8.8.8"]):
            with self.assertRaises(RuntimeError) as ctx:
                egress.enforce_endpoint_ip_allowlist(
                    endpoint_url="https://example.com",
                    raw_allowlist="10.0.0.0/8",
                    env_var_name="TEST_ALLOWED_IPS",
                    endpoint_label="de teste",
                )
        self.assertIn("TEST_ALLOWED_IPS", str(ctx.exception))

    def test_requires_valid_host_when_enabled(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            egress.enforce_endpoint_ip_allowlist(
                endpoint_url="http://",
                raw_allowlist="10.0.0.0/8",
                env_var_name="TEST_ALLOWED_IPS",
                endpoint_label="de teste",
            )
        self.assertIn("TEST_ALLOWED_IPS", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
