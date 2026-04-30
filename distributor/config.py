"""Configuration for the M3 Distribution Layer."""

# Portas locais: ver ../docs/PORTS.md
import os

from aws_kms_bootstrap import bootstrap_aws_kms_env

bootstrap_aws_kms_env()

ZMQ_ADDRESS = "tcp://localhost:5555"
ZMQ_SYNC_ADDRESS = "tcp://localhost:5557"
IPC_MODE = (os.environ.get("IPC_MODE") or "zmq").strip().lower()
SHM_MAPPING_NAME = (os.environ.get("SHM_MAPPING_NAME") or "Local\\PQMarketDataV1").strip()
SHM_SIZE_MB = int(os.environ.get("SHM_SIZE_MB", "64"))
SHM_FALLBACK_PROBE_TIMEOUT_MS = int(os.environ.get("SHM_FALLBACK_PROBE_TIMEOUT_MS", "3000"))
SHM_FALLBACK_PROBE_INTERVAL_MS = int(os.environ.get("SHM_FALLBACK_PROBE_INTERVAL_MS", "200"))
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
AGENT007_CHAT_TIMEOUT_S = float(os.environ.get("AGENT007_CHAT_TIMEOUT_S", "60"))
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
AGENT007_ALLOWED_IPS = (
    os.environ.get("AGENT007_ALLOWED_IPS")
    or os.environ.get("OPENROUTER_ALLOWED_IPS")
    or ""
).strip()
AGENT007_AUDIT_LOG_PATH = (os.environ.get("AGENT007_AUDIT_LOG_PATH") or "").strip()

# ---------------------------------------------------------------------------
# M8 — Copiloto IA Conversacional (Gemini Live API / WebSocket)
# ---------------------------------------------------------------------------

# Chave da Gemini API (Google AI Studio ou Vertex AI).
# A KMS pode injetar GOOGLE_API_KEY no startup; fallback para GEMINI_API_KEY.
GOOGLE_API_KEY = (
    os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("GEMINI_API_KEY")
    or ""
).strip()

# Modelo Live API da Google
GEMINI_LIVE_MODEL = (
    os.environ.get("GEMINI_LIVE_MODEL") or "gemini-3.1-flash-live-preview"
).strip()

# Voz Gemini: Puck, Charon, Kore, Fenrir, Aoede (default: Puck — clara e direta)
GEMINI_LIVE_VOICE = (os.environ.get("GEMINI_LIVE_VOICE") or "Puck").strip()

# Duração máxima de uma sessão de voz em segundos (padrão: 10 min)
VOICE_SESSION_MAX_DURATION_S = int(
    os.environ.get("VOICE_SESSION_MAX_DURATION_S", "600")
)

# Flag para habilitar/desabilitar o endpoint de voz (1 = habilitado)
VOICE_FUNCTIONS_ENABLED = (
    os.environ.get("VOICE_FUNCTIONS_ENABLED", "1").strip() == "1"
)

# WebSocket endpoint da Gemini Live API (BidiGenerateContent)
GEMINI_LIVE_WS_BASE = (
    "wss://generativelanguage.googleapis.com"
    "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

# ---------------------------------------------------------------------------
# M9 — RAG em Tempo Real
# ---------------------------------------------------------------------------

# Habilita pipeline RAG no distributor (ingestão + janelas + vetor + injeção)
RAG_ENABLED = (os.environ.get("RAG_ENABLED", "0").strip() == "1")

# Janela temporal para agregação de eventos de mercado (segundos)
RAG_WINDOW_SECONDS = int(os.environ.get("RAG_WINDOW_SECONDS", "300"))

# TTL dos vetores intraday (segundos). Default: 8 horas.
RAG_VECTOR_TTL_SECONDS = int(os.environ.get("RAG_VECTOR_TTL_SECONDS", "28800"))

# Quantidade de janelas retornadas por busca vetorial
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))

# Limite bruto de texto de contexto injetado no prompt
RAG_MAX_CONTEXT_CHARS = int(os.environ.get("RAG_MAX_CONTEXT_CHARS", "3200"))

# Prefixo dos tópicos no Redpanda/Kafka
RAG_TOPIC_PREFIX = (os.environ.get("RAG_TOPIC_PREFIX") or "pq").strip() or "pq"

# Brokers Redpanda/Kafka (csv: host:port,host:port). Vazio = streaming desativado.
RAG_REDPANDA_BROKERS = (os.environ.get("RAG_REDPANDA_BROKERS") or "").strip()

# Retenção alvo para tópicos de stream em milissegundos (8h default)
RAG_REDPANDA_RETENTION_MS = int(
    os.environ.get("RAG_REDPANDA_RETENTION_MS", "28800000")
)

# Backend vetorial cloud opcional (persistência entre restarts)
RAG_VECTOR_CLOUD_ENABLED = (
    os.environ.get("RAG_VECTOR_CLOUD_ENABLED", "0").strip() == "1"
)
RAG_VECTOR_CLOUD_PROVIDER = (
    os.environ.get("RAG_VECTOR_CLOUD_PROVIDER") or "pinecone"
).strip().lower()
RAG_VECTOR_CLOUD_TIMEOUT_S = float(
    os.environ.get("RAG_VECTOR_CLOUD_TIMEOUT_S", "1.5")
)

# Pinecone (REST index endpoint)
RAG_PINECONE_API_KEY = (os.environ.get("RAG_PINECONE_API_KEY") or "").strip()
RAG_PINECONE_INDEX_HOST = (os.environ.get("RAG_PINECONE_INDEX_HOST") or "").strip()
RAG_PINECONE_NAMESPACE = (
    os.environ.get("RAG_PINECONE_NAMESPACE") or "intraday"
).strip() or "intraday"

# Vectara (API v2)
RAG_VECTARA_API_KEY = (os.environ.get("RAG_VECTARA_API_KEY") or "").strip()
RAG_VECTARA_CORPUS_KEY = (os.environ.get("RAG_VECTARA_CORPUS_KEY") or "").strip()
RAG_VECTARA_BASE_URL = (
    os.environ.get("RAG_VECTARA_BASE_URL") or "https://api.vectara.io"
).strip().rstrip("/")

# Views materializadas locais (agregados intraday)
RAG_VIEWS_ENABLED = (os.environ.get("RAG_VIEWS_ENABLED", "1").strip() == "1")
RAG_VIEW_LAG_WARN_MS = int(os.environ.get("RAG_VIEW_LAG_WARN_MS", "1000"))
RAG_WALL_MIN_QTY = int(os.environ.get("RAG_WALL_MIN_QTY", "500"))
RAG_VIEWS_BACKEND = (os.environ.get("RAG_VIEWS_BACKEND") or "memory").strip().lower()
RAG_VIEWS_SQLITE_PATH = (os.environ.get("RAG_VIEWS_SQLITE_PATH") or "").strip()
