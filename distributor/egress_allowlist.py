"""Shared outbound endpoint IP allowlist helpers."""

from __future__ import annotations

import socket
from ipaddress import ip_address, ip_network
from typing import Any
from urllib.parse import urlparse


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_ip_allowlist(raw: str | None) -> list[Any]:
    values = _parse_csv(raw)
    networks: list[Any] = []
    for value in values:
        networks.append(ip_network(value, strict=False))
    return networks


def resolve_endpoint_ips(hostname: str, port: int = 443) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for family, _socktype, _proto, _canon, sockaddr in socket.getaddrinfo(hostname, port):
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip_raw = sockaddr[0]
        ip_norm = str(ip_address(ip_raw))
        if ip_norm in seen:
            continue
        seen.add(ip_norm)
        resolved.append(ip_norm)
    return resolved


def enforce_endpoint_ip_allowlist(
    *,
    endpoint_url: str,
    raw_allowlist: str | None,
    env_var_name: str,
    endpoint_label: str,
) -> dict[str, Any]:
    networks = parse_ip_allowlist(raw_allowlist)
    if not networks:
        return {"enabled": False, "endpoint_host": "", "resolved_ips": [], "allowed_ips": []}

    parsed = urlparse(str(endpoint_url).strip())
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        raise RuntimeError(
            f"{env_var_name} definido, mas URL do endpoint {endpoint_label} não possui host válido."
        )

    resolved_ips = resolve_endpoint_ips(hostname, parsed.port or 443)
    if not resolved_ips:
        raise RuntimeError(
            f"{env_var_name} definido, mas DNS não retornou IPs para host {hostname!r}."
        )

    disallowed = [
        ip for ip in resolved_ips if not any(ip_address(ip) in net for net in networks)
    ]
    if disallowed:
        raise RuntimeError(
            f"{env_var_name} bloqueou endpoint {endpoint_label}: "
            f"host={hostname}, ips_resolvidos={resolved_ips}, ips_bloqueados={disallowed}."
        )

    return {
        "enabled": True,
        "endpoint_host": hostname,
        "resolved_ips": resolved_ips,
        "allowed_ips": [str(net) for net in networks],
    }
