"""Tests for AWS KMS bootstrap loader."""

from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import aws_kms_bootstrap as kms


class _FlakyClient:
    def __init__(
        self,
        responses: dict[str, dict[str, str]],
        fails_before_success: int = 0,
        endpoint_url: str = "https://secretsmanager.sa-east-1.amazonaws.com",
    ) -> None:
        self._responses = responses
        self._fails_before_success = fails_before_success
        self.calls = 0
        self.meta = type("Meta", (), {"endpoint_url": endpoint_url})()

    def get_secret_value(self, *, SecretId: str):  # noqa: N803
        self.calls += 1
        if self.calls <= self._fails_before_success:
            raise RuntimeError("temporary aws failure")
        return self._responses[SecretId]


class _AlwaysFailClient:
    def __init__(self, endpoint_url: str = "https://secretsmanager.sa-east-1.amazonaws.com") -> None:
        self.meta = type("Meta", (), {"endpoint_url": endpoint_url})()

    def get_secret_value(self, *, SecretId: str):  # noqa: N803
        raise RuntimeError(f"cannot reach aws for {SecretId}")


class TestAwsKmsBootstrap(unittest.TestCase):
    def test_noop_when_disabled(self) -> None:
        out_env: dict[str, str] = {}
        loaded = kms.bootstrap_aws_kms_env(
            source_env={},
            target_env=out_env,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(loaded, {})
        self.assertEqual(out_env, {})

    def test_loads_with_retry_and_backoff(self) -> None:
        source_env = {
            "AWS_KMS_ENABLED": "1",
            "AWS_KMS_SECRET_MAP": "PROFIT_USER=prod/pq/profit-user",
        }
        target_env: dict[str, str] = {}
        sleep_calls: list[float] = []
        client = _FlakyClient(
            {"prod/pq/profit-user": {"SecretString": "user-from-kms"}},
            fails_before_success=2,
        )

        with mock.patch.object(kms, "_build_secretsmanager_client", return_value=client):
            loaded = kms.bootstrap_aws_kms_env(
                source_env=source_env,
                target_env=target_env,
                sleep_fn=sleep_calls.append,
            )

        self.assertEqual(loaded, {"PROFIT_USER": "prod/pq/profit-user"})
        self.assertEqual(target_env["PROFIT_USER"], "user-from-kms")
        self.assertEqual(sleep_calls, [0.25, 0.5])

    def test_json_field_selector(self) -> None:
        source_env = {
            "AWS_KMS_ENABLED": "true",
            "AWS_KMS_SECRET_MAP": '{"PROFIT_USER":"prod/pq/secret#user","PROFIT_PASSWORD":"prod/pq/secret#password"}',
        }
        target_env: dict[str, str] = {}
        client = _FlakyClient(
            {
                "prod/pq/secret": {
                    "SecretString": '{"user":"u-123","password":"p-456"}',
                }
            }
        )

        with mock.patch.object(kms, "_build_secretsmanager_client", return_value=client):
            kms.bootstrap_aws_kms_env(
                source_env=source_env,
                target_env=target_env,
                sleep_fn=lambda _: None,
            )

        self.assertEqual(target_env["PROFIT_USER"], "u-123")
        self.assertEqual(target_env["PROFIT_PASSWORD"], "p-456")

    def test_raises_clear_error_when_unreachable(self) -> None:
        source_env = {
            "AWS_KMS_ENABLED": "1",
            "AWS_KMS_SECRET_MAP": "OPENAI_API_KEY=prod/pq/openai",
            "AWS_KMS_MAX_RETRIES": "3",
        }
        with mock.patch.object(kms, "_build_secretsmanager_client", return_value=_AlwaysFailClient()):
            with self.assertRaises(RuntimeError) as ctx:
                kms.bootstrap_aws_kms_env(
                    source_env=source_env,
                    target_env={},
                    sleep_fn=lambda _: None,
                )
        self.assertIn(kms.AWS_UNAVAILABLE_MSG, str(ctx.exception))

    def test_allows_endpoint_when_ip_in_allowlist(self) -> None:
        source_env = {
            "AWS_KMS_ENABLED": "1",
            "AWS_KMS_SECRET_MAP": "PROFIT_USER=prod/pq/profit-user",
            "AWS_KMS_ALLOWED_IPS": "52.95.0.0/16",
        }
        target_env: dict[str, str] = {}
        client = _FlakyClient({"prod/pq/profit-user": {"SecretString": "user-from-kms"}})
        with mock.patch.object(kms, "_build_secretsmanager_client", return_value=client), mock.patch(
            "egress_allowlist.resolve_endpoint_ips",
            return_value=["52.95.1.2"],
        ):
            loaded = kms.bootstrap_aws_kms_env(
                source_env=source_env,
                target_env=target_env,
                sleep_fn=lambda _: None,
            )
        self.assertEqual(loaded, {"PROFIT_USER": "prod/pq/profit-user"})
        self.assertEqual(target_env["PROFIT_USER"], "user-from-kms")

    def test_blocks_endpoint_when_ip_outside_allowlist(self) -> None:
        source_env = {
            "AWS_KMS_ENABLED": "1",
            "AWS_KMS_SECRET_MAP": "PROFIT_USER=prod/pq/profit-user",
            "AWS_KMS_ALLOWED_IPS": "10.0.0.0/8",
        }
        target_env: dict[str, str] = {}
        client = _FlakyClient({"prod/pq/profit-user": {"SecretString": "user-from-kms"}})
        with mock.patch.object(kms, "_build_secretsmanager_client", return_value=client), mock.patch(
            "egress_allowlist.resolve_endpoint_ips",
            return_value=["52.95.1.2"],
        ):
            with self.assertRaises(RuntimeError) as ctx:
                kms.bootstrap_aws_kms_env(
                    source_env=source_env,
                    target_env=target_env,
                    sleep_fn=lambda _: None,
                )
        self.assertIn(kms.AWS_UNAVAILABLE_MSG, str(ctx.exception))
        self.assertIn("AWS_KMS_ALLOWED_IPS", str(ctx.exception))

    def test_writes_audit_log_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "kms_audit.jsonl"
            source_env = {
                "AWS_KMS_ENABLED": "1",
                "AWS_KMS_SECRET_MAP": "PROFIT_USER=prod/pq/profit-user",
                "AWS_KMS_AUDIT_LOG_PATH": str(audit_path),
            }
            target_env: dict[str, str] = {}
            client = _FlakyClient({"prod/pq/profit-user": {"SecretString": "user-from-kms"}})
            with mock.patch.object(kms, "_build_secretsmanager_client", return_value=client):
                kms.bootstrap_aws_kms_env(
                    source_env=source_env,
                    target_env=target_env,
                    sleep_fn=lambda _: None,
                )

            lines = [line.strip() for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 2)
            records = [json.loads(line) for line in lines]
            fetch = next(r for r in records if r.get("event") == "kms_secret_fetch" and r.get("status") == "ok")
            summary = next(r for r in records if r.get("event") == "kms_bootstrap_summary")
            self.assertEqual(fetch["env_var"], "PROFIT_USER")
            self.assertEqual(fetch["secret_id"], "prod/pq/profit-user")
            self.assertNotIn("user-from-kms", audit_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["loaded_count"], 1)


if __name__ == "__main__":
    unittest.main()
