<#
.SYNOPSIS
    Migra segredos de um .env para AWS Secrets Manager e gera o AWS_KMS_SECRET_MAP.

.DESCRIPTION
    Wrapper PowerShell para scripts/migrate_env_to_kms.py.
    Em modo dry-run (padrão), apenas exibe o mapeamento sem criar nada na AWS.

.EXAMPLE
    # Simula a migração (dry-run)
    .\scripts\migrate-env-to-kms.ps1 -DryRun -EnvFile .env `
        -Keys "OPENAI_API_KEY,PROFIT_USER,PROFIT_PASSWORD" `
        -Prefix "prod/pq" -Region "us-east-1"

.EXAMPLE
    # Migração real
    .\scripts\migrate-env-to-kms.ps1 -EnvFile .env `
        -Keys "OPENAI_API_KEY,PROFIT_USER,PROFIT_PASSWORD" `
        -Prefix "prod/pq" -Region "us-east-1"
#>

param(
    [string]$PythonExe = "python",
    [string]$EnvFile = "",
    [Parameter(Mandatory = $true)]
    [string]$Keys,
    [string]$Prefix = "prod/pq",
    [string]$Region = "",
    [switch]$DryRun,
    [string]$AuditLog = "",
    [ValidateSet("csv", "json", "both")]
    [string]$OutputFormat = "both",
    [string]$DescriptionPrefix = "Plataforma Quantitativa — migrado de .env: ",
    [switch]$FailOnMissing
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\migrate_env_to_kms.py"

if (-not (Test-Path $script)) {
    throw "Script não encontrado: $script"
}

$args = @(
    $script,
    "--keys", $Keys,
    "--prefix", $Prefix,
    "--output-format", $OutputFormat,
    "--description-prefix", $DescriptionPrefix
)

if ($EnvFile -and -not [string]::IsNullOrWhiteSpace($EnvFile)) {
    $envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $root $EnvFile }
    $args += @("--env-file", $envPath)
}

if ($Region -and -not [string]::IsNullOrWhiteSpace($Region)) {
    $args += @("--region", $Region)
}

if ($DryRun) {
    $args += "--dry-run"
}

if ($AuditLog -and -not [string]::IsNullOrWhiteSpace($AuditLog)) {
    $auditPath = if ([System.IO.Path]::IsPathRooted($AuditLog)) { $AuditLog } else { Join-Path $root $AuditLog }
    $args += @("--audit-log", $auditPath)
}

if ($FailOnMissing) {
    $args += "--fail-on-missing"
}

Write-Host "=== Migração .env → AWS Secrets Manager ===" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  [DRY-RUN] Nenhum secret será criado/atualizado." -ForegroundColor Yellow
}
Write-Host "  Keys:   $Keys" -ForegroundColor Gray
Write-Host "  Prefix: $Prefix" -ForegroundColor Gray
if ($Region) { Write-Host "  Region: $Region" -ForegroundColor Gray }

& $PythonExe @args
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "Migração finalizada com erros (exit=$exitCode)." -ForegroundColor Red
} else {
    Write-Host "Migração concluída com sucesso." -ForegroundColor Green
}

exit $exitCode
