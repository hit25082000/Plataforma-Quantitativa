param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$hookFile = Join-Path $root ".githooks\pre-commit"

if (-not (Test-Path $hookFile)) {
    throw "Hook file not found: $hookFile"
}

& git -C $root config core.hooksPath ".githooks"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to configure core.hooksPath"
}

Write-Host "Git hooks configured to .githooks" -ForegroundColor Green
