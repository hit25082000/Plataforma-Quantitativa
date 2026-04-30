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
    AGENT007_ALLOWED_IPS,
    AGENT007_AUDIT_LOG_PATH,
    AGENT007_BASE_URL,
    AGENT007_CHAT_MIN_INTERVAL_MS,
    AGENT007_CHAT_TIMEOUT_S,
    AGENT007_MODEL,
    AGENT007_OPENROUTER_APP_TITLE,
    AGENT007_OPENROUTER_HTTP_REFERER,
)
from egress_allowlist import enforce_endpoint_ip_allowlist
from security_audit import write_security_audit

logger = logging.getLogger(__name__)

_last_chat_by_client: Dict[str, float] = {}
_chat_metrics: Dict[str, int] = {
    "requests_total": 0,
    "success_total": 0,
    "errors_total": 0,
    "rate_limited": 0,
    "allowlist_blocked": 0,
    "http_errors": 0,
    "network_errors": 0,
    "invalid_response": 0,
}


def _inc_metric(key: str) -> None:
    _chat_metrics[key] = _chat_metrics.get(key, 0) + 1


def chat_metrics() -> Dict[str, int]:
    return dict(_chat_metrics)


def reset_chat_metrics() -> None:
    for key in list(_chat_metrics.keys()):
        _chat_metrics[key] = 0
    _last_chat_by_client.clear()


def _enforce_endpoint_ip_allowlist(url: str, raw_allowlist: str | None) -> dict[str, Any]:
    return enforce_endpoint_ip_allowlist(
        endpoint_url=url,
        raw_allowlist=raw_allowlist,
        env_var_name="AGENT007_ALLOWED_IPS",
        endpoint_label="do provider",
    )


def check_rate_limit(client_id: str) -> Tuple[bool, str]:
    now = time.monotonic() * 1000
    last = _last_chat_by_client.get(client_id, 0.0)
    if now - last < AGENT007_CHAT_MIN_INTERVAL_MS:
        _inc_metric("rate_limited")
        wait = int(AGENT007_CHAT_MIN_INTERVAL_MS - (now - last))
        return False, f"Aguarde {wait} ms antes de nova mensagem."
    _last_chat_by_client[client_id] = now
    return True, ""


def run_agent007_chat(
    user_messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    rag_context: str = "",
) -> Tuple[bool, str]:
    """Retorna (ok, texto_ou_erro)."""
    _inc_metric("requests_total")

    if not AGENT007_API_KEY:
        _inc_metric("errors_total")
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
    rag_ctx = (rag_context or "").strip()
    if rag_ctx:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Contexto intraday recuperado por RAG (use apenas como apoio factual):\n"
                    f"{rag_ctx}"
                ),
            }
        )
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

    allowlist_audit: dict[str, Any] = {
        "enabled": False,
        "endpoint_host": "",
        "resolved_ips": [],
        "allowed_ips": [],
    }
    try:
        allowlist_audit = _enforce_endpoint_ip_allowlist(url, AGENT007_ALLOWED_IPS)
    except Exception as e:  # noqa: BLE001
        _inc_metric("errors_total")
        _inc_metric("allowlist_blocked")
        write_security_audit(
            AGENT007_AUDIT_LOG_PATH or None,
            {
                "event": "agent007_chat_request",
                "status": "error",
                "error": str(e),
                "provider_base_url": AGENT007_BASE_URL,
                "model": AGENT007_MODEL,
                "allowlist_enabled": 1,
            },
            source="agent007_chat",
        )
        logger.warning("Agent007 chat blocked by allowlist: %s", e)
        return False, "Acesso ao provedor bloqueado pela allowlist de IP."

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    t0 = time.perf_counter_ns()
    try:
        with urllib.request.urlopen(req, timeout=AGENT007_CHAT_TIMEOUT_S) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        _inc_metric("errors_total")
        _inc_metric("http_errors")
        err_body = e.read().decode(errors="replace")[:500]
        logger.warning("Agent007 chat HTTP %s: %s", e.code, err_body)
        write_security_audit(
            AGENT007_AUDIT_LOG_PATH or None,
            {
                "event": "agent007_chat_request",
                "status": "error",
                "error_kind": "http",
                "http_status": int(e.code),
                "provider_base_url": AGENT007_BASE_URL,
                "model": AGENT007_MODEL,
                "latency_ms": round((time.perf_counter_ns() - t0) / 1_000_000.0, 3),
                "allowlist_enabled": int(allowlist_audit["enabled"]),
                "endpoint_host": allowlist_audit["endpoint_host"],
                "endpoint_ips": allowlist_audit["resolved_ips"],
                "allowed_ips": allowlist_audit["allowed_ips"],
            },
            source="agent007_chat",
        )
        return False, f"Erro do provedor ({e.code})."
    except Exception as e:
        _inc_metric("errors_total")
        _inc_metric("network_errors")
        logger.warning("Agent007 chat failed: %s", e)
        write_security_audit(
            AGENT007_AUDIT_LOG_PATH or None,
            {
                "event": "agent007_chat_request",
                "status": "error",
                "error_kind": "network",
                "error": str(e),
                "provider_base_url": AGENT007_BASE_URL,
                "model": AGENT007_MODEL,
                "latency_ms": round((time.perf_counter_ns() - t0) / 1_000_000.0, 3),
                "allowlist_enabled": int(allowlist_audit["enabled"]),
                "endpoint_host": allowlist_audit["endpoint_host"],
                "endpoint_ips": allowlist_audit["resolved_ips"],
                "allowed_ips": allowlist_audit["allowed_ips"],
            },
            source="agent007_chat",
        )
        return False, "Falha de rede ao contatar o modelo."

    try:
        choice = data["choices"][0]
        msg = choice["message"]
        text = (msg.get("content") or "").strip()
        if not text:
            _inc_metric("errors_total")
            _inc_metric("invalid_response")
            write_security_audit(
                AGENT007_AUDIT_LOG_PATH or None,
                {
                    "event": "agent007_chat_request",
                    "status": "error",
                    "error_kind": "empty_response",
                    "provider_base_url": AGENT007_BASE_URL,
                    "model": AGENT007_MODEL,
                    "latency_ms": round((time.perf_counter_ns() - t0) / 1_000_000.0, 3),
                    "allowlist_enabled": int(allowlist_audit["enabled"]),
                    "endpoint_host": allowlist_audit["endpoint_host"],
                    "endpoint_ips": allowlist_audit["resolved_ips"],
                    "allowed_ips": allowlist_audit["allowed_ips"],
                },
                source="agent007_chat",
            )
            return False, "Resposta vazia do modelo."
        _inc_metric("success_total")
        write_security_audit(
            AGENT007_AUDIT_LOG_PATH or None,
            {
                "event": "agent007_chat_request",
                "status": "ok",
                "provider_base_url": AGENT007_BASE_URL,
                "model": AGENT007_MODEL,
                "latency_ms": round((time.perf_counter_ns() - t0) / 1_000_000.0, 3),
                "allowlist_enabled": int(allowlist_audit["enabled"]),
                "endpoint_host": allowlist_audit["endpoint_host"],
                "endpoint_ips": allowlist_audit["resolved_ips"],
                "allowed_ips": allowlist_audit["allowed_ips"],
            },
            source="agent007_chat",
        )
        return True, text
    except (KeyError, IndexError, TypeError):
        _inc_metric("errors_total")
        _inc_metric("invalid_response")
        write_security_audit(
            AGENT007_AUDIT_LOG_PATH or None,
            {
                "event": "agent007_chat_request",
                "status": "error",
                "error_kind": "invalid_payload",
                "provider_base_url": AGENT007_BASE_URL,
                "model": AGENT007_MODEL,
                "latency_ms": round((time.perf_counter_ns() - t0) / 1_000_000.0, 3),
                "allowlist_enabled": int(allowlist_audit["enabled"]),
                "endpoint_host": allowlist_audit["endpoint_host"],
                "endpoint_ips": allowlist_audit["resolved_ips"],
                "allowed_ips": allowlist_audit["allowed_ips"],
            },
            source="agent007_chat",
        )
        return False, "Formato de resposta inesperado."
