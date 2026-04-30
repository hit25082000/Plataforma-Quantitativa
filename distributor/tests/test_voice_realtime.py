"""Testes unitários para voice_realtime (M8 — Gemini Live API)."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from typing import Any

# Garante que distributor/ esteja no sys.path para import direto
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Stub de config para isolar o módulo
# ---------------------------------------------------------------------------

def _make_config_stub(**overrides: Any) -> types.ModuleType:
    cfg = types.ModuleType("config")
    cfg.GOOGLE_API_KEY = overrides.get("GOOGLE_API_KEY", "AIza-test-key")
    cfg.GEMINI_LIVE_MODEL = overrides.get("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
    cfg.GEMINI_LIVE_VOICE = overrides.get("GEMINI_LIVE_VOICE", "Puck")
    cfg.GEMINI_LIVE_WS_BASE = overrides.get(
        "GEMINI_LIVE_WS_BASE",
        "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
    )
    cfg.VOICE_FUNCTIONS_ENABLED = overrides.get("VOICE_FUNCTIONS_ENABLED", True)
    cfg.VOICE_SESSION_MAX_DURATION_S = overrides.get("VOICE_SESSION_MAX_DURATION_S", 600)
    # Stubs adicionais usados indiretamente
    cfg.AGENT007_API_KEY = ""
    cfg.AGENT007_ALLOWED_IPS = ""
    cfg.AGENT007_AUDIT_LOG_PATH = ""
    cfg.AGENT007_BASE_URL = "https://openrouter.ai/api/v1"
    cfg.AGENT007_MODEL = "openai/gpt-4o-mini"
    cfg.AGENT007_CHAT_MIN_INTERVAL_MS = 2000
    cfg.AGENT007_CHAT_TIMEOUT_S = 60.0
    cfg.AGENT007_OPENROUTER_HTTP_REFERER = ""
    cfg.AGENT007_OPENROUTER_APP_TITLE = "Plataforma Quantitativa"
    # Stubs de módulos auxiliares
    sa = types.ModuleType("security_audit")
    sa.write_security_audit = lambda *a, **kw: None  # type: ignore
    sa.security_audit_metrics = lambda: {}  # type: ignore
    sys.modules.setdefault("security_audit", sa)
    ea = types.ModuleType("egress_allowlist")
    ea.enforce_endpoint_ip_allowlist = lambda **kw: {}  # type: ignore
    sys.modules.setdefault("egress_allowlist", ea)
    return cfg


# ---------------------------------------------------------------------------
# Testes de create_realtime_session
# ---------------------------------------------------------------------------

class TestCreateRealtimeSession(unittest.TestCase):

    def setUp(self):
        sys.modules.pop("voice_realtime", None)

    def _load_module(self, **cfg_overrides: Any):
        sys.modules["config"] = _make_config_stub(**cfg_overrides)
        sys.modules.pop("voice_realtime", None)
        import voice_realtime as vr
        return vr

    def test_disabled_by_flag(self):
        vr = self._load_module(VOICE_FUNCTIONS_ENABLED=False)
        result = vr.create_realtime_session()
        self.assertFalse(result["ok"])
        self.assertIn("desabilitado", result["error"])

    def test_no_api_key(self):
        vr = self._load_module(GOOGLE_API_KEY="")
        result = vr.create_realtime_session()
        self.assertFalse(result["ok"])
        self.assertIn("GOOGLE_API_KEY", result["error"])

    def test_returns_ws_url_with_key(self):
        vr = self._load_module()
        result = vr.create_realtime_session()
        self.assertTrue(result["ok"], result)
        self.assertIn("ws_url", result)
        self.assertIn("AIza-test-key", result["ws_url"])
        self.assertIn("generativelanguage.googleapis.com", result["ws_url"])

    def test_returns_setup_message(self):
        vr = self._load_module()
        result = vr.create_realtime_session()
        self.assertIn("setup_message", result)
        setup = result["setup_message"]
        self.assertIn("setup", setup)
        inner = setup["setup"]
        # Modelo com prefixo "models/"
        self.assertTrue(inner["model"].startswith("models/"))
        self.assertIn("gemini-3.1-flash-live-preview", inner["model"])

    def test_setup_message_has_tools(self):
        vr = self._load_module()
        result = vr.create_realtime_session()
        inner = result["setup_message"]["setup"]
        tools = inner.get("tools", [])
        self.assertEqual(len(tools), 1)
        fn_decls = tools[0].get("functionDeclarations", [])
        names = [f["name"] for f in fn_decls]
        self.assertIn("analyze_order_book", names)
        self.assertIn("get_current_signal", names)
        self.assertIn("get_wall_status", names)
        self.assertIn("get_vwap_position", names)

    def test_function_declarations_use_uppercase_type(self):
        """Gemini exige tipos uppercase (OBJECT, STRING...) nas declarations."""
        vr = self._load_module()
        result = vr.create_realtime_session()
        fn_decls = result["setup_message"]["setup"]["tools"][0]["functionDeclarations"]
        for fn in fn_decls:
            params = fn.get("parameters", {})
            self.assertEqual(params.get("type", ""), "OBJECT",
                             f"{fn['name']}: type deve ser 'OBJECT'")

    def test_provider_is_gemini(self):
        vr = self._load_module()
        result = vr.create_realtime_session()
        self.assertEqual(result.get("provider"), "gemini")

    def test_max_duration_s_returned(self):
        vr = self._load_module(VOICE_SESSION_MAX_DURATION_S=300)
        result = vr.create_realtime_session()
        self.assertEqual(result["max_duration_s"], 300)

    def test_voice_config_in_setup(self):
        vr = self._load_module(GEMINI_LIVE_VOICE="Charon")
        result = vr.create_realtime_session()
        speech_cfg = (
            result["setup_message"]["setup"]
            ["generationConfig"]["speechConfig"]
            ["voiceConfig"]["prebuiltVoiceConfig"]
        )
        self.assertEqual(speech_cfg["voiceName"], "Charon")

    def test_system_instruction_in_portuguese(self):
        vr = self._load_module()
        result = vr.create_realtime_session()
        instruction = (
            result["setup_message"]["setup"]
            ["systemInstruction"]["parts"][0]["text"]
        )
        self.assertIn("português", instruction.lower())
        self.assertIn("Copiloto 007", instruction)

    def test_metrics_increment_on_success(self):
        vr = self._load_module()
        vr._voice_metrics["sessions_created"] = 0
        vr.create_realtime_session()
        self.assertEqual(vr._voice_metrics["sessions_created"], 1)

    def tearDown(self):
        sys.modules.pop("voice_realtime", None)
        sys.modules.pop("config", None)


# ---------------------------------------------------------------------------
# Testes de execute_function_call
# ---------------------------------------------------------------------------

class TestExecuteFunctionCall(unittest.TestCase):

    def setUp(self):
        sys.modules.pop("voice_realtime", None)
        sys.modules["config"] = _make_config_stub()
        import voice_realtime as vr
        self.vr = vr

    def _snap(self, **kw: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "ticker": "WINFUT",
            "last_price": 130000.0,
            "vwap": 129800.0,
            "urgency_0_100": 55,
            "signal": "green",
            "weis_side": "buy",
            "price_vs_vwap": "above",
            "entry_buy_valid": True,
            "entry_filter_reason": None,
            "recent_inversions": [],
            "alerts": [],
            "macd_direction": "buy",
        }
        base.update(kw)
        return base

    def test_analyze_order_book_buy(self):
        result = self.vr.execute_function_call("analyze_order_book", self._snap())
        self.assertEqual(result["weis_side"], "buy")
        self.assertIn("compradora", result["interpretation"])

    def test_analyze_order_book_sell(self):
        result = self.vr.execute_function_call("analyze_order_book", self._snap(weis_side="sell"))
        self.assertIn("vendedora", result["interpretation"])

    def test_analyze_order_book_neutral(self):
        result = self.vr.execute_function_call("analyze_order_book", self._snap(weis_side="unknown"))
        self.assertIn("neutro", result["interpretation"].lower())

    def test_get_current_signal_green(self):
        result = self.vr.execute_function_call("get_current_signal", self._snap(signal="green"))
        self.assertEqual(result["signal"], "green")
        self.assertIn("verde", result["signal_label"].lower())

    def test_get_current_signal_red(self):
        result = self.vr.execute_function_call("get_current_signal", self._snap(signal="red"))
        self.assertIn("vermelho", result["signal_label"].lower())

    def test_get_wall_status_empty(self):
        result = self.vr.execute_function_call("get_wall_status", self._snap(), active_walls=[])
        self.assertEqual(result["walls_count"], 0)
        self.assertIn("Nenhuma", result["interpretation"])

    def test_get_wall_status_with_walls(self):
        walls = [{"price": 130000, "side": "sell", "offer_id": 1}]
        result = self.vr.execute_function_call("get_wall_status", self._snap(), active_walls=walls)
        self.assertEqual(result["walls_count"], 1)
        self.assertEqual(result["walls"][0]["price"], 130000)

    def test_get_vwap_above(self):
        result = self.vr.execute_function_call("get_vwap_position", self._snap())
        self.assertEqual(result["price_vs_vwap"], "above")
        self.assertAlmostEqual(result["distance_to_vwap"], 200.0)

    def test_get_vwap_below(self):
        snap = self._snap(last_price=129700.0, vwap=129800.0, price_vs_vwap="below")
        result = self.vr.execute_function_call("get_vwap_position", snap)
        self.assertAlmostEqual(result["distance_to_vwap"], -100.0)

    def test_unknown_function(self):
        result = self.vr.execute_function_call("nonexistent_fn", self._snap())
        self.assertIn("error", result)
        self.assertIn("nonexistent_fn", result["error"])

    def test_none_snapshot_returns_defaults(self):
        result = self.vr.execute_function_call("get_current_signal", None)
        self.assertEqual(result["signal"], "neutral")

    def test_function_calls_metric(self):
        self.vr._voice_metrics["function_calls_total"] = 0
        self.vr.execute_function_call("get_current_signal", self._snap())
        self.vr.execute_function_call("get_vwap_position", self._snap())
        self.assertEqual(self.vr._voice_metrics["function_calls_total"], 2)

    def tearDown(self):
        sys.modules.pop("voice_realtime", None)
        sys.modules.pop("config", None)


# ---------------------------------------------------------------------------
# Testes de voice_metrics
# ---------------------------------------------------------------------------

class TestVoiceMetrics(unittest.TestCase):

    def setUp(self):
        sys.modules.pop("voice_realtime", None)
        sys.modules["config"] = _make_config_stub()
        import voice_realtime as vr
        self.vr = vr

    def test_metrics_keys_present(self):
        m = self.vr.voice_metrics()
        for key in ("sessions_created", "sessions_failed", "function_calls_total", "function_calls_failed"):
            self.assertIn(key, m)

    def test_metrics_returns_copy(self):
        m = self.vr.voice_metrics()
        m["sessions_created"] = 99999
        self.assertNotEqual(self.vr._voice_metrics["sessions_created"], 99999)

    def tearDown(self):
        sys.modules.pop("voice_realtime", None)
        sys.modules.pop("config", None)


if __name__ == "__main__":
    unittest.main()
