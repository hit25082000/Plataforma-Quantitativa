# Verificacao local automatizavel do plano docs/plans/2026-04-26-volume-profile-sato-correcao-v1-tarefas.md
# Engine: volume_profile_tests, trade_reconciler_tests; frontend: typecheck+build; Tauri: cargo build
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root "engine\CMakeLists.txt"))) {
    throw "Raiz do repo nao encontrada a partir de $PSScriptRoot"
}

function Invoke-Step {
    param([string]$Name, [scriptblock]$Block)
    Write-Host "==> $Name"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}

try {
    $engineOut = Join-Path $root "engine\build\Debug\volume_profile_tests.exe"
    $reconOut = Join-Path $root "engine\build\Debug\trade_reconciler_tests.exe"
    if (-not (Test-Path $engineOut)) {
        throw "Nao encontrado: $engineOut. Configure e compile: cmake -B engine/build -S engine && cmake --build engine/build --config Debug"
    }
    Invoke-Step "engine volume_profile_tests" { & $engineOut }
    if (-not (Test-Path $reconOut)) {
        throw "Nao encontrado: $reconOut"
    }
    Invoke-Step "engine trade_reconciler_tests" { & $reconOut }

    $tauri = Join-Path $root "app\src-tauri"
    Push-Location $tauri
    try { Invoke-Step "cargo build (src-tauri)" { cargo build } }
    finally { Pop-Location }

    $fe = Join-Path $root "frontend"
    Push-Location $fe
    try {
        Invoke-Step "npm run typecheck" { npm run typecheck }
        Invoke-Step "npm run build" { npm run build }
    }
    finally { Pop-Location }

    Write-Host "verify-vp-sato-correcao-v1: OK"
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
