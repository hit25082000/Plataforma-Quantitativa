"""Configuration for the M3 Distribution Layer."""

# Portas locais: ver ../docs/PORTS.md
import os

ZMQ_ADDRESS = "tcp://localhost:5555"
ZMQ_SYNC_ADDRESS = "tcp://localhost:5557"
WS_PORT = int(os.environ.get("WS_PORT", "8000"))
WS_HOST = "127.0.0.1"  # apenas localhost (single machine)
# Alinhar com a engine: env DOM_SNAPSHOT_PUBLISH_MIN_MS (default 100 ms no ZmqPublisher).
# O distributor só descarta dom_snapshot extra se chegar mais rápido que isto.
DOM_THROTTLE_MS = int(os.environ.get("DOM_THROTTLE_MS", "100"))
MARKET_QUEUE_MAXSIZE = int(os.environ.get("MARKET_QUEUE_MAXSIZE", "20000"))
MARKET_QUEUE_DOM_SOFT_LIMIT_PCT = int(
    os.environ.get("MARKET_QUEUE_DOM_SOFT_LIMIT_PCT", "70")
)
ROUTER_METRICS_LOG_EVERY_MS = int(os.environ.get("ROUTER_METRICS_LOG_EVERY_MS", "5000"))
BROKER_SNAPSHOT_EVERY_MS = int(os.environ.get("BROKER_SNAPSHOT_EVERY_MS", "1000"))

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
