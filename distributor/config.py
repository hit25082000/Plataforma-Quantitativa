"""Configuration for the M3 Distribution Layer."""

# Portas locais: ver ../docs/PORTS.md
import os

ZMQ_ADDRESS = "tcp://localhost:5555"
ZMQ_SYNC_ADDRESS = "tcp://localhost:5557"
WS_PORT = int(os.environ.get("WS_PORT", "8000"))
WS_HOST = "127.0.0.1"  # apenas localhost (single machine)
DOM_THROTTLE_MS = 100  # máx 10 dom_snapshots/s para o frontend
MARKET_QUEUE_MAXSIZE = 1000  # descarta se frontend não consumir

# Agente 007 (ver distributor/agent_007.py)
_weis_mode = (os.environ.get("AGENT007_WEIS_MODE") or "proxy").strip().lower()
AGENT007_WEIS_MODE = (
    _weis_mode if _weis_mode in ("proxy", "ocr", "manual") else "proxy"
)
AGENT007_BROADCAST_MIN_MS = int(os.environ.get("AGENT007_BROADCAST_MIN_MS", "200"))
AGENT007_BREAKOUT_COOLDOWN_MS = int(
    os.environ.get("AGENT007_BREAKOUT_COOLDOWN_MS", "60000")
)
AGENT007_VWAP_EPSILON_PCT = float(
    os.environ.get("AGENT007_VWAP_EPSILON_PCT", "0.0001")
)
AGENT007_CHAT_MIN_INTERVAL_MS = int(
    os.environ.get("AGENT007_CHAT_MIN_INTERVAL_MS", "2000")
)
# Chave: AGENT007_API_KEY ou OPENROUTER_API_KEY (OpenRouter)
AGENT007_API_KEY = (
    os.environ.get("AGENT007_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
).strip()
# OpenRouter: https://openrouter.ai/api/v1 — modelo no formato provedor/nome
AGENT007_MODEL = (os.environ.get("AGENT007_MODEL") or "openai/gpt-4o-mini").strip()
AGENT007_BASE_URL = (
    os.environ.get("AGENT007_BASE_URL") or "https://openrouter.ai/api/v1"
).rstrip("/")
# Cabeçalhos opcionais OpenRouter (ranking / atribuição)
AGENT007_OPENROUTER_HTTP_REFERER = (
    os.environ.get("AGENT007_OPENROUTER_HTTP_REFERER")
    or os.environ.get("OPENROUTER_HTTP_REFERER")
    or ""
).strip()
AGENT007_OPENROUTER_APP_TITLE = (
    os.environ.get("AGENT007_OPENROUTER_APP_TITLE") or "Plataforma Quantitativa"
).strip()
