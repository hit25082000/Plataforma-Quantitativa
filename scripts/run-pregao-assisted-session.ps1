param(
    [string]$PythonExe = "python",
    [string]$OutDir,
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$TracePath = "",
    [ValidateRange(60, 120)]
    [int]$DurationSec = 90,
    [double]$TimeoutSeconds = 2.5,
    [switch]$DryRun = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runnerScript = Join-Path $root "scripts\run_pregao_assisted_session.py"

if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found: $runnerScript"
}

if (-not $OutDir -or [string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $root "distributor\logs\pregao-assisted-session-$stamp"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$args = @(
    $runnerScript,
    "--out-dir", $OutDir,
    "--base-url", $BaseUrl,
    "--duration-sec", "$DurationSec",
    "--timeout-seconds", "$TimeoutSeconds"
)

if ($TracePath -and -not [string]::IsNullOrWhiteSpace($TracePath)) {
    $args += @("--trace-path", $TracePath)
}
if ($DryRun) {
    $args += "--dry-run"
}

Write-Host "=== Pregao assisted session ===" -ForegroundColor Cyan
Write-Host "out=$OutDir duration=$DurationSec dry_run=$DryRun base=$BaseUrl" -ForegroundColor Gray
& $PythonExe @args
$exitCode = $LASTEXITCODE

$manifest = Join-Path $OutDir "session.manifest.json"
$commands = Join-Path $OutDir "commands.md"
$checklist = Join-Path $OutDir "operator_checklist.md"
if (-not (Test-Path $manifest)) {
    throw "Missing manifest: $manifest"
}
if (-not (Test-Path $commands)) {
    throw "Missing commands file: $commands"
}
if (-not (Test-Path $checklist)) {
    throw "Missing checklist file: $checklist"
}

Write-Host "Verified: $manifest" -ForegroundColor Green
Write-Host "Verified: $commands" -ForegroundColor Green
Write-Host "Verified: $checklist" -ForegroundColor Green
if ($exitCode -ne 0) {
    exit $exitCode
}
