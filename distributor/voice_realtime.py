"""M8 — Copiloto IA Conversacional: sessão Gemini Live API (WebSocket).

Arquitetura:
1. create_gemini_live_session() constrói os parâmetros de conexão WebSocket
   (URL com API key + setup_message) e os devolve ao frontend.
2. O frontend abre o WebSocket diretamente com a Google Gemini Live API,
   envia áudio PCM16 em chunks e recebe áudio PCM16 de resposta.
3. Function Calling: a IA invoca uma função via toolCall → frontend faz
   POST /api/voice/function-call no distributor → Agent007.get_snapshot()
   → resultado retornado via toolResponse no WebSocket pelo frontend.

O distributor nunca faz proxy de áudio — apenas fornece os params de
conexão e executa as funções de mercado.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from config import (
    GEMINI_LIVE_MODEL,
    GEMINI_LIVE_VOICE,
    GEMINI_LIVE_WS_BASE,
    GOOGLE_API_KEY,
    VOICE_FUNCTIONS_ENABLED,
    VOICE_SESSION_MAX_DURATION_S,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema de ferramentas — formato Gemini Live (functionDeclarations)
# ---------------------------------------------------------------------------

GEMINI_FUNCTION_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "analyze_order_book",
        "description": (
            "Retorna o desequilíbrio de agressão atual no livro de ordens: "
            "saldo de agressão comprador vs vendedor nos últimos 30 segundos, "
            "inversões de fluxo recentes e urgência do sinal (0-100)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_current_signal",
        "description": (
            "Retorna o sinal atual do Agente 007: verde (squeeze comprador), "
            "vermelho (liquidação/estope) ou neutro, junto com o lado Weis e "
            "a urgência atual (0-100). Use quando o trader perguntar sobre o "
            "sinal, tendência ou direção do mercado."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_wall_status",
        "description": (
            "Retorna as muralhas (ordens grandes ≥500 lotes) ativas no livro de "
            "ofertas detectadas pelo motor C++. Inclui preço e lado de cada muralha."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_vwap_position",
        "description": (
            "Retorna o preço atual e a VWAP institucional, e se o preço está "
            "acima, abaixo ou na VWAP. Use quando o trader perguntar sobre "
            "preço, VWAP ou posição relativa."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": [],
        },
    },
]

# ---------------------------------------------------------------------------
# Instrução de sistema
# ---------------------------------------------------------------------------

GEMINI_SYSTEM_PROMPT = (
    "Você é o Copiloto 007, assistente de leitura de fluxo de ordens da "
    "Plataforma Quantitativa. Você ajuda traders de day-trade a interpretar o "
    "DOM e Times & Trades da B3 em tempo real. "
    "Responda SEMPRE em português do Brasil, de forma curta e objetiva — "
    "máximo 2 frases por resposta. "
    "Use as funções disponíveis para consultar dados de mercado antes de "
    "responder sobre preço, sinal ou fluxo. "
    "Nunca invente números; se não tiver dados, diga 'ainda sem dados de mercado'. "
    "Tom: direto, técnico, sem rodeios — como um operador experiente."
)

# ---------------------------------------------------------------------------
# Métricas de sessão
# ---------------------------------------------------------------------------

_voice_metrics: Dict[str, int] = {
    "sessions_created": 0,
    "sessions_failed": 0,
    "function_calls_total": 0,
    "function_calls_failed": 0,
}


def voice_metrics() -> Dict[str, int]:
    """Retorna cópia das métricas de voz."""
    return dict(_voice_metrics)


def _inc(key: str) -> None:
    _voice_metrics[key] = _voice_metrics.get(key, 0) + 1


# ---------------------------------------------------------------------------
# Criação de sessão Gemini Live (retorna params de conexão WebSocket)
# ---------------------------------------------------------------------------


def create_realtime_session() -> Dict[str, Any]:
    """Constrói os parâmetros de conexão para a Gemini Live API.

    Não faz chamada HTTP — apenas valida a chave e monta o ws_url e o
    setup_message que o frontend enviará logo após abrir o WebSocket.

    Returns:
        dict com campos:
          - ok (bool)
          - ws_url (str): URL WebSocket com API key embutida (segura pois
            só é retornada para localhost)
          - setup_message (dict): primeira mensagem a enviar após conectar
          - model (str)
          - max_duration_s (int)
          - provider (str): "gemini"
          - error (str | None): mensagem de erro se ok=False
    """
    if not VOICE_FUNCTIONS_ENABLED:
        return {
            "ok": False,
            "error": "Copiloto de voz desabilitado (VOICE_FUNCTIONS_ENABLED=0).",
        }

    if not GOOGLE_API_KEY:
        return {
            "ok": False,
            "error": (
                "Copiloto de voz indisponível: configure GOOGLE_API_KEY ou "
                "GEMINI_API_KEY no processo do distributor (AWS Secrets Manager ou .env)."
            ),
        }

    ws_url = f"{GEMINI_LIVE_WS_BASE}?key={GOOGLE_API_KEY}"

    # Setup message: primeira mensagem enviada pelo frontend após conexão WebSocket
    setup_message: Dict[str, Any] = {
        "setup": {
            "model": f"models/{GEMINI_LIVE_MODEL}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": GEMINI_LIVE_VOICE,
                        }
                    }
                },
                # thinkingLevel minimal → menor latência (padrão recomendado para Live)
                "thinkingConfig": {"thinkingBudget": 0},
            },
            "systemInstruction": {
                "parts": [{"text": GEMINI_SYSTEM_PROMPT}]
            },
            "tools": [{"functionDeclarations": GEMINI_FUNCTION_DECLARATIONS}],
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "disabled": False,
                    "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
                    "endOfSpeechSensitivity": "END_SENSITIVITY_LOW",
                    "silenceDurationMs": 600,
                    "prefixPaddingMs": 300,
                }
            },
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }

    t0 = time.perf_counter_ns()
    logger.info(
        "Gemini Live session params built in %.1f ms",
        (time.perf_counter_ns() - t0) / 1_000_000.0,
    )

    _inc("sessions_created")
    return {
        "ok": True,
        "ws_url": ws_url,
        "setup_message": setup_message,
        "model": GEMINI_LIVE_MODEL,
        "voice": GEMINI_LIVE_VOICE,
        "max_duration_s": VOICE_SESSION_MAX_DURATION_S,
        "provider": "gemini",
    }


# ---------------------------------------------------------------------------
# Execução de Function Calls (invocadas pela IA via toolCall)
# ---------------------------------------------------------------------------


def execute_function_call(
    function_name: str,
    agent007_snapshot: Optional[Dict[str, Any]],
    active_walls: Optional[list[Any]] = None,
) -> Dict[str, Any]:
    """Executa uma das 4 funções de mercado e retorna o resultado.

    Args:
        function_name: nome da função invocada pela IA.
        agent007_snapshot: snapshot atual do Agent007 (de get_snapshot()).
        active_walls: lista de muralhas ativas [{price, side, offer_id}].

    Returns:
        dict serializável com o resultado da função.
    """
    _inc("function_calls_total")
    snap = agent007_snapshot or {}

    if function_name == "analyze_order_book":
        return _fn_analyze_order_book(snap)
    elif function_name == "get_current_signal":
        return _fn_get_current_signal(snap)
    elif function_name == "get_wall_status":
        return _fn_get_wall_status(active_walls or [])
    elif function_name == "get_vwap_position":
        return _fn_get_vwap_position(snap)
    else:
        _inc("function_calls_failed")
        return {"error": f"Função desconhecida: {function_name}"}


def _fn_analyze_order_book(snap: Dict[str, Any]) -> Dict[str, Any]:
    inversions = snap.get("recent_inversions") or []
    alerts = snap.get("alerts") or []
    weis = snap.get("weis_side", "unknown")
    return {
        "urgency": snap.get("urgency_0_100", 0),
        "weis_side": weis,
        "recent_inversions_count": len(inversions),
        "recent_inversions": inversions[:3],
        "recent_alerts": alerts[-3:],
        "interpretation": (
            "Pressão compradora dominante"
            if weis == "buy"
            else "Pressão vendedora dominante"
            if weis == "sell"
            else "Fluxo neutro ou indefinido"
        ),
    }


def _fn_get_current_signal(snap: Dict[str, Any]) -> Dict[str, Any]:
    signal = snap.get("signal", "neutral")
    label_map = {
        "green": "Sinal verde — squeeze comprador (acima do médio + Weis compradora)",
        "red": "Sinal vermelho — liquidação/estope (abaixo do médio + Weis vendedora)",
        "neutral": "Sinal neutro",
    }
    return {
        "signal": signal,
        "signal_label": label_map.get(signal, signal),
        "urgency": snap.get("urgency_0_100", 0),
        "weis_side": snap.get("weis_side", "unknown"),
        "macd_direction": snap.get("macd_direction"),
        "entry_buy_valid": snap.get("entry_buy_valid", True),
        "entry_filter_reason": snap.get("entry_filter_reason"),
        "ticker": snap.get("ticker", ""),
    }


def _fn_get_wall_status(walls: list[Any]) -> Dict[str, Any]:
    if not walls:
        return {
            "walls_count": 0,
            "walls": [],
            "interpretation": "Nenhuma muralha ativa detectada no DOM.",
        }
    return {
        "walls_count": len(walls),
        "walls": walls[:10],
        "interpretation": f"{len(walls)} muralha(s) ativa(s) no livro de ofertas.",
    }


def _fn_get_vwap_position(snap: Dict[str, Any]) -> Dict[str, Any]:
    price = snap.get("last_price", 0)
    vwap = snap.get("vwap", 0)
    pos = snap.get("price_vs_vwap", "at")
    pos_label = {
        "above": "acima da VWAP — zona de compadores",
        "below": "abaixo da VWAP — zona de vendedores",
        "at": "na VWAP — zona de equilíbrio",
    }.get(pos, pos)
    dist = round(price - vwap, 2) if price > 0 and vwap > 0 else None
    return {
        "last_price": price,
        "vwap": vwap,
        "price_vs_vwap": pos,
        "price_vs_vwap_label": pos_label,
        "distance_to_vwap": dist,
        "ticker": snap.get("ticker", ""),
    }
