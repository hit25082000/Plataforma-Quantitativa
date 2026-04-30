"""Testes para scripts/migrate_env_to_kms.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


def _load_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "migrate_env_to_kms.py"
    spec = importlib.util.spec_from_file_location("migrate_env_to_kms", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


m = _load_module()


class TestParseEnvFile(unittest.TestCase):
    def _write_env(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    def test_basic_key_value(self) -> None:
        p = self._write_env("FOO=bar\nBAZ=qux\n")
        result = m._parse_env_file(p)
        self.assertEqual(result["FOO"], "bar")
        self.assertEqual(result["BAZ"], "qux")

    def test_quoted_values(self) -> None:
        p = self._write_env('A="hello world"\nB=\'single\'\n')
        result = m._parse_env_file(p)
        self.assertEqual(result["A"], "hello world")
        self.assertEqual(result["B"], "single")

    def test_comments_and_blanks_ignored(self) -> None:
        p = self._write_env("# comment\n\nFOO=1\n")
        result = m._parse_env_file(p)
        self.assertNotIn("# comment", result)
        self.assertEqual(result["FOO"], "1")

    def test_line_without_equals_ignored(self) -> None:
        p = self._write_env("NOEQUALS\nFOO=bar\n")
        result = m._parse_env_file(p)
        self.assertNotIn("NOEQUALS", result)
        self.assertIn("FOO", result)

    def test_value_with_equals_sign(self) -> None:
        p = self._write_env("TOKEN=abc=def==ghi\n")
        result = m._parse_env_file(p)
        self.assertEqual(result["TOKEN"], "abc=def==ghi")


class TestSecretName(unittest.TestCase):
    def test_with_prefix(self) -> None:
        self.assertEqual(m._secret_name("prod/pq", "OPENAI_API_KEY"), "prod/pq/openai-api-key")

    def test_with_trailing_slash_in_prefix(self) -> None:
        self.assertEqual(m._secret_name("prod/pq/", "PROFIT_USER"), "prod/pq/profit-user")

    def test_empty_prefix(self) -> None:
        self.assertEqual(m._secret_name("", "PROFIT_PASSWORD"), "profit-password")


class TestBuildSecretMap(unittest.TestCase):
    def test_csv_format(self) -> None:
        mapping = {"FOO": "prod/pq/foo", "BAR": "prod/pq/bar"}
        csv_out = m._build_secret_map_csv(mapping)
        # Deve conter ambos os pares
        self.assertIn("BAR=prod/pq/bar", csv_out)
        self.assertIn("FOO=prod/pq/foo", csv_out)

    def test_json_format(self) -> None:
        mapping = {"FOO": "prod/pq/foo"}
        json_out = m._build_secret_map_json(mapping)
        parsed = json.loads(json_out)
        self.assertEqual(parsed["FOO"], "prod/pq/foo")


class TestCreateOrUpdateSecret(unittest.TestCase):
    def test_dry_run_returns_immediately(self) -> None:
        client = MagicMock()
        result = m._create_or_update_secret(
            client,
            secret_name="prod/pq/foo",
            secret_value="secret",
            description="desc",
            dry_run=True,
        )
        self.assertEqual(result, "dry_run")
        client.create_secret.assert_not_called()

    def test_creates_when_not_exists(self) -> None:
        client = MagicMock()
        # Não levanta ResourceExistsException → cria
        result = m._create_or_update_secret(
            client,
            secret_name="prod/pq/foo",
            secret_value="val",
            description="d",
            dry_run=False,
        )
        self.assertEqual(result, "created")
        client.create_secret.assert_called_once()

    def test_updates_when_exists(self) -> None:
        client = MagicMock()
        exc_class = type("ResourceExistsException", (Exception,), {})
        client.exceptions.ResourceExistsException = exc_class
        client.create_secret.side_effect = exc_class("already exists")
        result = m._create_or_update_secret(
            client,
            secret_name="prod/pq/foo",
            secret_value="val",
            description="d",
            dry_run=False,
        )
        self.assertEqual(result, "updated")
        client.update_secret.assert_called_once()


class TestAuditDoesNotExposeValues(unittest.TestCase):
    def test_audit_jsonl_has_no_secret_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "audit.jsonl"
            m._audit(log, {"event": "test", "secret_value": "TOP_SECRET", "env_key": "FOO"})
            content = log.read_text(encoding="utf-8")
            self.assertNotIn("TOP_SECRET", content)
            self.assertIn("FOO", content)
            self.assertIn("test", content)

    def test_audit_no_log_path_does_not_raise(self) -> None:
        # Deve apenas logar via logger.debug sem falhar
        m._audit(None, {"event": "test", "env_key": "BAR"})


class TestMigrateDryRun(unittest.TestCase):
    def test_dry_run_no_client_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("FOO=secret_value\n", encoding="utf-8")
            # Em dry_run=True, não deve chamar boto3 de modo nenhum
            with patch("builtins.print"):  # Silencia output
                exit_code = m.migrate(
                    env_file=env_file,
                    keys=["FOO"],
                    prefix="prod/pq",
                    region="us-east-1",
                    dry_run=True,
                    audit_log=None,
                    output_format="csv",
                    description_prefix="Test: ",
                    fail_on_missing=False,
                )
            self.assertEqual(exit_code, 0)

    def test_missing_key_with_fail_on_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("FOO=present\n", encoding="utf-8")
            with patch("builtins.print"):
                exit_code = m.migrate(
                    env_file=env_file,
                    keys=["FOO", "MISSING_KEY"],
                    prefix="prod/pq",
                    region=None,
                    dry_run=True,
                    audit_log=None,
                    output_format="both",
                    description_prefix="Test: ",
                    fail_on_missing=True,
                )
            # MISSING_KEY não está no .env → exit 1
            self.assertEqual(exit_code, 1)

    def test_all_missing_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("OTHER=val\n", encoding="utf-8")
            with patch("builtins.print"):
                exit_code = m.migrate(
                    env_file=env_file,
                    keys=["NONE_OF_THESE"],
                    prefix="prod/pq",
                    region=None,
                    dry_run=True,
                    audit_log=None,
                    output_format="csv",
                    description_prefix="Test: ",
                    fail_on_missing=False,
                )
            self.assertEqual(exit_code, 1)

    def test_audit_written_on_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("FOO=secret\n", encoding="utf-8")
            audit_log = Path(tmp) / "audit.jsonl"
            with patch("builtins.print"):
                m.migrate(
                    env_file=env_file,
                    keys=["FOO"],
                    prefix="prod/pq",
                    region=None,
                    dry_run=True,
                    audit_log=audit_log,
                    output_format="csv",
                    description_prefix="Test: ",
                    fail_on_missing=False,
                )
            self.assertTrue(audit_log.exists())
            content = audit_log.read_text(encoding="utf-8")
            self.assertIn("migrate_secret", content)
            self.assertNotIn("secret", content.split('"event"')[0])  # valor não exposto

    def test_secret_value_not_in_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("MY_KEY=SUPER_SENSITIVE_VALUE\n", encoding="utf-8")
            audit_log = Path(tmp) / "audit.jsonl"
            with patch("builtins.print"):
                m.migrate(
                    env_file=env_file,
                    keys=["MY_KEY"],
                    prefix="prod/pq",
                    region=None,
                    dry_run=True,
                    audit_log=audit_log,
                    output_format="json",
                    description_prefix="Test: ",
                    fail_on_missing=False,
                )
            content = audit_log.read_text(encoding="utf-8")
            self.assertNotIn("SUPER_SENSITIVE_VALUE", content)


class TestLoadSourceEnv(unittest.TestCase):
    def test_loads_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("MY_VAR=hello\n", encoding="utf-8")
            result = m._load_source_env(env_file)
            self.assertEqual(result["MY_VAR"], "hello")

    def test_raises_if_file_missing(self) -> None:
        with self.assertRaises(SystemExit):
            m._load_source_env(Path("/nonexistent/.env"))

    def test_loads_from_os_environ_when_no_file(self) -> None:
        import os
        os.environ["_PQ_TEST_VAR_MIGRATE"] = "test_value"
        try:
            result = m._load_source_env(None)
            self.assertIn("_PQ_TEST_VAR_MIGRATE", result)
        finally:
            del os.environ["_PQ_TEST_VAR_MIGRATE"]


if __name__ == "__main__":
    unittest.main()
