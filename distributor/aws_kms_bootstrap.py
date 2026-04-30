"""AWS KMS-backed secret bootstrap for startup credentials.

This module loads secrets from AWS Secrets Manager (encrypted with KMS) and
injects them into process environment variables before config constants are
materialized.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any

from egress_allowlist import enforce_endpoint_ip_allowlist
from security_audit import write_security_audit

logger = logging.getLogger(__name__)

AWS_UNAVAILABLE_MSG = "Não foi possível acessar credenciais. Verifique conexão com AWS."


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _parse_positive_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _enforce_endpoint_ip_allowlist(client: Any, raw_allowlist: str | None) -> dict[str, Any]:
    endpoint_url = (
        str(getattr(getattr(client, "meta", object()), "endpoint_url", "") or "").strip()
    )
    if not endpoint_url:
        raise RuntimeError("AWS_KMS_ALLOWED_IPS definido, mas endpoint_url do cliente AWS está vazio.")
    return enforce_endpoint_ip_allowlist(
        endpoint_url=endpoint_url,
        raw_allowlist=raw_allowlist,
        env_var_name="AWS_KMS_ALLOWED_IPS",
        endpoint_label="AWS",
    )


def _audit_write(
    path: str | None,
    payload: dict[str, Any],
    source_env: Mapping[str, str] | None = None,
) -> None:
    write_security_audit(
        path,
        payload,
        source="aws_kms_bootstrap",
        env=source_env,
    )


def _parse_secret_map(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}

    if text.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("AWS_KMS_SECRET_MAP deve ser objeto JSON.")
        out: dict[str, str] = {}
        for key, value in data.items():
            env_name = str(key).strip()
            secret_ref = str(value).strip()
            if not env_name or not secret_ref:
                continue
            out[env_name] = secret_ref
        return out

    out: dict[str, str] = {}
    for item in text.split(","):
        pair = item.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"Par inválido em AWS_KMS_SECRET_MAP: {pair}")
        env_name, secret_ref = pair.split("=", 1)
        env_name = env_name.strip()
        secret_ref = secret_ref.strip()
        if not env_name or not secret_ref:
            continue
        out[env_name] = secret_ref
    return out


def _split_secret_ref(secret_ref: str) -> tuple[str, str | None]:
    ref = secret_ref.strip()
    if "#" not in ref:
        return ref, None
    secret_id, field = ref.rsplit("#", 1)
    secret_id = secret_id.strip()
    field = field.strip()
    return secret_id, (field or None)


def _extract_secret_value(response: dict[str, Any]) -> str:
    if "SecretString" in response and response["SecretString"] is not None:
        value = response["SecretString"]
        if isinstance(value, str):
            return value
        return str(value)

    if "SecretBinary" in response and response["SecretBinary"] is not None:
        blob = response["SecretBinary"]
        if isinstance(blob, (bytes, bytearray)):
            raw = bytes(blob)
        elif isinstance(blob, str):
            raw = base64.b64decode(blob)
        else:
            raise TypeError("SecretBinary em formato não suportado.")
        return raw.decode("utf-8")

    raise KeyError("Resposta do Secrets Manager sem SecretString/SecretBinary.")


def _select_secret_field(secret_value: str, field: str | None) -> str:
    if not field:
        return secret_value
    parsed = json.loads(secret_value)
    if not isinstance(parsed, dict):
        raise ValueError(f"Segredo não é JSON object para campo #{field}.")
    if field not in parsed:
        raise KeyError(f"Campo #{field} ausente no segredo.")
    value = parsed[field]
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _build_secretsmanager_client(region: str | None) -> Any:
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "AWS_KMS_ENABLED=1, mas boto3 não está instalado no ambiente do distributor."
        ) from exc

    kwargs: dict[str, str] = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client("secretsmanager", **kwargs)


def _fetch_with_retry(
    *,
    client: Any,
    secret_id: str,
    field: str | None,
    retries: int,
    base_backoff_ms: int,
    sleep_fn: Callable[[float], None],
) -> tuple[str, int]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.get_secret_value(SecretId=secret_id)
            return _select_secret_field(_extract_secret_value(response), field), attempt
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            delay_s = (base_backoff_ms / 1000.0) * (2 ** (attempt - 1))
            logger.warning(
                "AWS secret fetch falhou (tentativa %s/%s, secret=%s): %s",
                attempt,
                retries,
                secret_id,
                exc,
            )
            sleep_fn(delay_s)

    assert last_exc is not None
    raise last_exc


def bootstrap_aws_kms_env(
    *,
    source_env: Mapping[str, str] | None = None,
    target_env: MutableMapping[str, str] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Load configured secrets and inject them into environment variables.

    Env knobs:
    - AWS_KMS_ENABLED (or KMS_ENABLED): 1/true/yes/on/sim
    - AWS_KMS_SECRET_MAP (or KMS_SECRET_MAP):
      * JSON: {"PROFIT_USER":"prod/pq/profit-user"}
      * CSV:  PROFIT_USER=prod/pq/profit-user,PROFIT_PASSWORD=prod/pq/profit-pass  # allow-secret
      * Supports JSON field extraction with '#': SECRET_ID#field
    - AWS_KMS_REQUIRED_KEYS (or KMS_REQUIRED_KEYS): comma-separated env names
    - AWS_KMS_REGION (or AWS_REGION / AWS_DEFAULT_REGION)
    - AWS_KMS_MAX_RETRIES (default 3)
    - AWS_KMS_BASE_BACKOFF_MS (default 250)
    - AWS_KMS_ALLOWED_IPS (or KMS_ALLOWED_IPS): lista CSV de IP/CIDR permitidos para endpoint AWS
    - AWS_KMS_AUDIT_LOG_PATH (or KMS_AUDIT_LOG_PATH): arquivo JSONL para auditoria de acesso
    """

    env = source_env if source_env is not None else os.environ
    out_env = target_env if target_env is not None else os.environ

    enabled = _is_truthy(env.get("AWS_KMS_ENABLED")) or _is_truthy(env.get("KMS_ENABLED"))
    if not enabled:
        return {}

    raw_map = (env.get("AWS_KMS_SECRET_MAP") or env.get("KMS_SECRET_MAP") or "").strip()
    secret_map = _parse_secret_map(raw_map)
    if not secret_map:
        raise RuntimeError("AWS_KMS_ENABLED=1, mas AWS_KMS_SECRET_MAP/KMS_SECRET_MAP está vazio.")

    retries = _parse_positive_int(env.get("AWS_KMS_MAX_RETRIES"), 3)
    base_backoff_ms = _parse_positive_int(env.get("AWS_KMS_BASE_BACKOFF_MS"), 250)
    required_keys = _parse_csv(env.get("AWS_KMS_REQUIRED_KEYS") or env.get("KMS_REQUIRED_KEYS"))
    if not required_keys:
        required_keys = list(secret_map.keys())
    audit_log_path = (
        (env.get("AWS_KMS_AUDIT_LOG_PATH") or "").strip()
        or (env.get("KMS_AUDIT_LOG_PATH") or "").strip()
        or None
    )

    region = (
        (env.get("AWS_KMS_REGION") or "").strip()
        or (env.get("AWS_REGION") or "").strip()
        or (env.get("AWS_DEFAULT_REGION") or "").strip()
        or None
    )
    allowed_ips_raw = (env.get("AWS_KMS_ALLOWED_IPS") or env.get("KMS_ALLOWED_IPS") or "").strip()
    allowlist_audit: dict[str, Any] = {
        "enabled": False,
        "endpoint_host": "",
        "resolved_ips": [],
        "allowed_ips": [],
    }

    try:
        client = _build_secretsmanager_client(region)
        allowlist_audit = _enforce_endpoint_ip_allowlist(client, allowed_ips_raw)
        loaded_refs: dict[str, str] = {}
        for env_name, secret_ref in secret_map.items():
            secret_id, field = _split_secret_ref(secret_ref)
            secret_value, attempts_used = _fetch_with_retry(
                client=client,
                secret_id=secret_id,
                field=field,
                retries=retries,
                base_backoff_ms=base_backoff_ms,
                sleep_fn=sleep_fn,
            )
            out_env[env_name] = secret_value
            loaded_refs[env_name] = secret_ref
            _audit_write(
                audit_log_path,
                {
                    "event": "kms_secret_fetch",
                    "status": "ok",
                    "env_var": env_name,
                    "secret_id": secret_id,
                    "field": field or "",
                    "attempts_used": attempts_used,
                    "retries_configured": retries,
                    "region": region or "",
                    "allowlist_enabled": int(allowlist_audit["enabled"]),
                    "endpoint_host": allowlist_audit["endpoint_host"],
                    "endpoint_ips": allowlist_audit["resolved_ips"],
                },
                env,
            )
    except Exception as exc:  # noqa: BLE001
        _audit_write(
            audit_log_path,
            {
                "event": "kms_secret_fetch",
                "status": "error",
                "error": str(exc),
                "region": region or "",
                "allowlist_enabled": int(allowlist_audit["enabled"]),
                "endpoint_host": allowlist_audit["endpoint_host"],
                "endpoint_ips": allowlist_audit["resolved_ips"],
                "allowed_ips": allowlist_audit["allowed_ips"],
            },
            env,
        )
        raise RuntimeError(f"{AWS_UNAVAILABLE_MSG} ({exc})") from exc

    missing = [name for name in required_keys if not str(out_env.get(name, "")).strip()]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"{AWS_UNAVAILABLE_MSG} (credenciais ausentes: {joined})")

    _audit_write(
        audit_log_path,
        {
            "event": "kms_bootstrap_summary",
            "status": "ok",
            "loaded_count": len(loaded_refs),
            "loaded_env_vars": sorted(loaded_refs.keys()),
            "region": region or "",
            "allowlist_enabled": int(allowlist_audit["enabled"]),
            "endpoint_host": allowlist_audit["endpoint_host"],
            "endpoint_ips": allowlist_audit["resolved_ips"],
            "allowed_ips": allowlist_audit["allowed_ips"],
        },
        env,
    )

    return loaded_refs
