"""Testes do scanner de segredos usado no pre-commit."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_scan_module():
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "scripts" / "scan_secrets.py"
    spec = importlib.util.spec_from_file_location("scan_secrets", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load scan module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = _load_scan_module()


class TestScanSecrets(unittest.TestCase):
    def test_detects_openai_key(self) -> None:
        text = 'OPENAI_API_KEY="sk-proj-ABCDEF1234567890abcdef1234567890"\n'  # allow-secret
        findings = scan.scan_text("env.sample", text)
        rules = {item.rule for item in findings}
        self.assertIn("openai_api_key", rules)
        self.assertIn("high_entropy_secret_assignment", rules)

    def test_ignores_placeholders(self) -> None:
        text = "\n".join(
            [
                "OPENAI_API_KEY=sk-...",
                "AWS_SECRET_ACCESS_KEY=changeme",
                "BROKER_PASSWORD=<secret>",
                "",
            ]
        )
        findings = scan.scan_text("config.env", text)
        self.assertEqual(findings, [])

    def test_detects_password_assignment(self) -> None:
        text = "PROFIT_DLL_PASSWORD=MinhaSenha12345\n"  # allow-secret
        findings = scan.scan_text("prod.env", text)
        rules = {item.rule for item in findings}
        self.assertIn("password_assignment", rules)


if __name__ == "__main__":
    unittest.main()
