# Script canónico: scripts/build-installer.ps1 (raiz do repositório).
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
& (Join-Path $ProjectRoot "scripts\build-installer.ps1")
exit $LASTEXITCODE
