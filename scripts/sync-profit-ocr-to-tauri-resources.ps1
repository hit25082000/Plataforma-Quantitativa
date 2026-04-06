# Copia profit_ocr_service.py (fonte: distributor/) para app/src-tauri/resources/ (bundle Tauri).
# Invocado por run-dev.ps1 e build-installer.ps1.

param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$src = Join-Path $RepoRoot "distributor\profit_ocr_service.py"
$dstDir = Join-Path $RepoRoot "app\src-tauri\resources"
$dst = Join-Path $dstDir "profit_ocr_service.py"

if (-not (Test-Path $src)) {
    throw "Ficheiro em falta: $src"
}

New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item $src $dst -Force
Write-Host "profit_ocr_service.py sincronizado para Tauri resources." -ForegroundColor Gray
