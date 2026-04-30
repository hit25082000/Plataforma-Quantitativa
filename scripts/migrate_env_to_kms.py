#!/usr/bin/env python3
"""Migração de segredos de .env para AWS Secrets Manager.

Lê variáveis de um arquivo .env ou do ambiente atual, cria (ou atualiza) cada
secret no AWS Secrets Manager e imprime o AWS_KMS_SECRET_MAP resultante,
pronto para copiar ao .env ou aos launchers.

Uso básico:
    python scripts/migrate_env_to_kms.py \\
        --env-file .env \\
        --keys OPENAI_API_KEY,PROFIT_USER,PROFIT_PASSWORD \\
        --prefix prod/pq/ \\
        --region us-east-1 \\
        --dry-run

Modo não-dry-run cria/atualiza os secrets na AWS.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers de .env
# ---------------------------------------------------------------------------


def _parse_env_file(path: Path) -> dict[str, str]:
    """Lê um arquivo .env e retorna {chave: valor}."""
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Remove aspas simples/duplas envolvendo o valor
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def _load_source_env(env_file: Path | None) -> dict[str, str]:
    """Carrega variáveis do arquivo .env ou do ambiente do processo."""
    if env_file is not None:
        if not env_file.exists():
            raise SystemExit(f"Arquivo .env não encontrado: {env_file}")
        return _parse_env_file(env_file)
    return dict(os.environ)


# ---------------------------------------------------------------------------
# Helpers de secret name
# ---------------------------------------------------------------------------


def _secret_name(prefix: str, env_key: str) -> str:
    """Gera o nome do secret a partir do prefixo e da chave de env."""
    prefix = prefix.rstrip("/")
    slug = env_key.lower().replace("_", "-")
    return f"{prefix}/{slug}" if prefix else slug


# ---------------------------------------------------------------------------
# Auditoria simples (sem expor valores)
# ---------------------------------------------------------------------------


def _audit(audit_log: Path | None, payload: dict[str, Any]) -> None:
    """Grava linha JSONL de auditoria sem expor valores de segredos."""
    safe = {k: v for k, v in payload.items() if k != "secret_value"}
    safe["ts_epoch"] = time.time()
    line = json.dumps(safe, ensure_ascii=False)
    if audit_log is not None:
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        with audit_log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    else:
        logger.debug("AUDIT: %s", line)


# ---------------------------------------------------------------------------
# Operações AWS
# ---------------------------------------------------------------------------


def _build_client(region: str | None) -> Any:
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "boto3 não está instalado. Execute: pip install boto3"
        ) from exc
    kwargs: dict[str, str] = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client("secretsmanager", **kwargs)


def _create_or_update_secret(
    client: Any,
    *,
    secret_name: str,
    secret_value: str,
    description: str,
    dry_run: bool,
) -> str:
    """Cria ou atualiza um secret. Retorna 'created', 'updated' ou 'dry_run'."""
    if dry_run:
        return "dry_run"

    try:
        client.create_secret(
            Name=secret_name,
            SecretString=secret_value,
            Description=description,
        )
        return "created"
    except client.exceptions.ResourceExistsException:
        client.update_secret(
            SecretId=secret_name,
            SecretString=secret_value,
            Description=description,
        )
        return "updated"


# ---------------------------------------------------------------------------
# Geração do AWS_KMS_SECRET_MAP
# ---------------------------------------------------------------------------


def _build_secret_map_csv(mapping: dict[str, str]) -> str:
    """Gera AWS_KMS_SECRET_MAP no formato CSV: ENV_VAR=secret/name,..."""
    return ",".join(f"{env}={secret}" for env, secret in sorted(mapping.items()))


def _build_secret_map_json(mapping: dict[str, str]) -> str:
    """Gera AWS_KMS_SECRET_MAP no formato JSON."""
    return json.dumps(dict(sorted(mapping.items())), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------


def migrate(
    *,
    env_file: Path | None,
    keys: list[str],
    prefix: str,
    region: str | None,
    dry_run: bool,
    audit_log: Path | None,
    output_format: str,
    description_prefix: str,
    fail_on_missing: bool,
) -> int:
    """Executa a migração e retorna exit code."""
    source_env = _load_source_env(env_file)

    missing = [k for k in keys if not source_env.get(k, "").strip()]
    if missing:
        msg = f"Chaves não encontradas ou vazias no .env: {', '.join(missing)}"
        if fail_on_missing:
            logger.error(msg)
            return 1
        logger.warning(msg)

    present_keys = [k for k in keys if source_env.get(k, "").strip()]
    if not present_keys:
        logger.error("Nenhuma chave disponível para migrar.")
        return 1

    client = None
    if not dry_run:
        client = _build_client(region)

    secret_mapping: dict[str, str] = {}  # ENV_VAR -> secret_name
    errors: list[str] = []

    for env_key in present_keys:
        value = source_env[env_key]
        sname = _secret_name(prefix, env_key)
        description = f"{description_prefix}{env_key}"

        _audit(
            audit_log,
            {
                "event": "migrate_secret_start",
                "env_key": env_key,
                "secret_name": sname,
                "dry_run": dry_run,
                "region": region or "",
            },
        )

        try:
            action = _create_or_update_secret(
                client,
                secret_name=sname,
                secret_value=value,
                description=description,
                dry_run=dry_run,
            )
            secret_mapping[env_key] = sname
            _audit(
                audit_log,
                {
                    "event": "migrate_secret_done",
                    "env_key": env_key,
                    "secret_name": sname,
                    "action": action,
                    "dry_run": dry_run,
                    "region": region or "",
                },
            )
            status_label = f"[DRY-RUN] " if dry_run else ""
            logger.info("%s%s → %s (%s)", status_label, env_key, sname, action)
        except Exception as exc:  # noqa: BLE001
            _audit(
                audit_log,
                {
                    "event": "migrate_secret_error",
                    "env_key": env_key,
                    "secret_name": sname,
                    "error": str(exc),
                    "dry_run": dry_run,
                    "region": region or "",
                },
            )
            logger.error("Erro ao migrar %s → %s: %s", env_key, sname, exc)
            errors.append(env_key)

    if not secret_mapping:
        logger.error("Nenhum secret foi migrado com sucesso.")
        return 1

    # Exibe o AWS_KMS_SECRET_MAP resultante
    print("\n" + "=" * 60)
    if dry_run:
        print("  [DRY-RUN] Nenhum secret foi criado/atualizado na AWS.")
    print(f"  Secrets migrados: {len(secret_mapping)}/{len(present_keys)}")
    if errors:
        print(f"  Erros: {', '.join(errors)}")
    print("=" * 60)
    print("\n# Adicione ao seu .env (ou passe como env var ao distributor):\n")
    print(f"AWS_KMS_ENABLED=1")
    print(f"AWS_KMS_REGION={region or '<sua-região>'}")

    if output_format in ("csv", "both"):
        print(f"\n# Formato CSV:")
        print(f"AWS_KMS_SECRET_MAP={_build_secret_map_csv(secret_mapping)}")
    if output_format in ("json", "both"):
        print(f"\n# Formato JSON:")
        print(f"AWS_KMS_SECRET_MAP='{_build_secret_map_json(secret_mapping)}'")

    print()
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Migra segredos de .env para AWS Secrets Manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Caminho para o arquivo .env (padrão: lê do ambiente atual)",
    )
    ap.add_argument(
        "--keys",
        type=str,
        required=True,
        help="Chaves a migrar, separadas por vírgula (ex: OPENAI_API_KEY,PROFIT_USER)",
    )
    ap.add_argument(
        "--prefix",
        type=str,
        default="prod/pq",
        help="Prefixo para os secret names na AWS (padrão: prod/pq)",
    )
    ap.add_argument(
        "--region",
        type=str,
        default=None,
        help="Região AWS (padrão: usa AWS_REGION / AWS_DEFAULT_REGION)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simula a migração sem criar/atualizar nada na AWS",
    )
    ap.add_argument(
        "--audit-log",
        type=Path,
        default=None,
        help="Caminho para arquivo JSONL de auditoria (sem valores sensíveis)",
    )
    ap.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="both",
        help="Formato do AWS_KMS_SECRET_MAP gerado (padrão: both)",
    )
    ap.add_argument(
        "--description-prefix",
        type=str,
        default="Plataforma Quantitativa — migrado de .env: ",
        help="Prefixo para a descrição dos secrets na AWS",
    )
    ap.add_argument(
        "--fail-on-missing",
        action="store_true",
        default=False,
        help="Aborta se alguma chave especificada não existir no .env",
    )
    ap.add_argument(
        "--json-map",
        action="store_true",
        default=False,
        help="Imprime apenas o secret map JSON (para uso programático)",
    )
    return ap


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    ap = build_arg_parser()
    args = ap.parse_args()

    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    if not keys:
        raise SystemExit("--keys não pode ser vazio")

    region = args.region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None

    if args.json_map:
        # Modo silencioso para uso programático (ex: wraper PS1)
        source_env = _load_source_env(args.env_file)
        mapping = {
            k: _secret_name(args.prefix, k)
            for k in keys
            if source_env.get(k, "").strip()
        }
        print(json.dumps(mapping, ensure_ascii=False))
        return

    exit_code = migrate(
        env_file=args.env_file,
        keys=keys,
        prefix=args.prefix,
        region=region,
        dry_run=args.dry_run,
        audit_log=args.audit_log,
        output_format=args.output_format,
        description_prefix=args.description_prefix,
        fail_on_missing=args.fail_on_missing,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
