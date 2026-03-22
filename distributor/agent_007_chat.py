"""Chat Agente 007: rate limit + chamada OpenAI-compatible (stdlib)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

from config import (
    AGENT007_API_KEY,
    AGENT007_BASE_URL,
    AGENT007_CHAT_MIN_INTERVAL_MS,
    AGENT007_MODEL,
    AGENT007_OPENROUTER_APP_TITLE,
    AGENT007_OPENROUTER_HTTP_REFERER,
)

logger = logging.getLogger(__name__)

_last_chat_by_client: Dict[str, float] = {}


def check_rate_limit(client_id: str) -> Tuple[bool, str]:
    now = time.monotonic() * 1000
    last = _last_chat_by_client.get(client_id, 0.0)
    if now - last < AGENT007_CHAT_MIN_INTERVAL_MS:
        wait = int(AGENT007_CHAT_MIN_INTERVAL_MS - (now - last))
        return False, f"Aguarde {wait} ms antes de nova mensagem."
    _last_chat_by_client[client_id] = now
    return True, ""


def run_agent007_chat(
    user_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
) -> Tuple[bool, str]:
    """Retorna (ok, texto_ou_erro)."""
    if not AGENT007_API_KEY:
        return False, (
            "Chat com IA desativado: defina AGENT007_API_KEY ou OPENROUTER_API_KEY "
            "no processo do distributor (OpenRouter: https://openrouter.ai/keys)."
        )

    system = (
        "Você é o Agente 007, assistente de leitura de fluxo na Plataforma Quantitativa. "
        "Responda em português, de forma curta e objetiva. "
        "Use apenas o snapshot JSON fornecido como fonte de fatos sobre preço, VWAP, sinais e alertas; "
        "não invente números. Se o snapshot estiver vazio ou sem preço, diga que ainda não há dados."
    )
    snap_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Snapshot do mercado (tempo real):\n```json\n{snap_json}\n```",
        },
    ]
    for m in user_messages[-12:]:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        messages.append({"role": role, "content": content})

    url = f"{AGENT007_BASE_URL}/chat/completions"
    body = json.dumps(
        {
            "model": AGENT007_MODEL,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 512,
        }
    ).encode("utf-8")

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AGENT007_API_KEY}",
    }
    # OpenRouter recomenda HTTP-Referer e X-Title para atribuição
    base_lower = AGENT007_BASE_URL.lower()
    if "openrouter.ai" in base_lower:
        if AGENT007_OPENROUTER_HTTP_REFERER:
            headers["HTTP-Referer"] = AGENT007_OPENROUTER_HTTP_REFERER
        if AGENT007_OPENROUTER_APP_TITLE:
            headers["X-Title"] = AGENT007_OPENROUTER_APP_TITLE

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")[:500]
        logger.warning("Agent007 chat HTTP %s: %s", e.code, err_body)
        return False, f"Erro do provedor ({e.code})."
    except Exception as e:
        logger.warning("Agent007 chat failed: %s", e)
        return False, "Falha de rede ao contatar o modelo."

    try:
        choice = data["choices"][0]
        msg = choice["message"]
        text = (msg.get("content") or "").strip()
        if not text:
            return False, "Resposta vazia do modelo."
        return True, text
    except (KeyError, IndexError, TypeError):
        return False, "Formato de resposta inesperado."
