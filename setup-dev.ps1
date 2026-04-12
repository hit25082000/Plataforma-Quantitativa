param(
    [switch]$IncludeInstallerDeps
)

$ErrorActionPreference = "Stop"

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )
    if (-not (Test-Command $Name)) {
        throw "Comando '$Name' nao encontrado. $InstallHint"
    }
}

function Ensure-Vcpkg {
    param([string]$RootPath = "C:\vcpkg")

    if (-not (Test-Path $RootPath)) {
        Write-Host "Clonando vcpkg em $RootPath..." -ForegroundColor Cyan
        git clone https://github.com/microsoft/vcpkg.git $RootPath
    }

    $bootstrap = Join-Path $RootPath "bootstrap-vcpkg.bat"
    if (-not (Test-Path $bootstrap)) {
        throw "bootstrap-vcpkg.bat nao encontrado em $RootPath"
    }

    Write-Host "Bootstrap do vcpkg..." -ForegroundColor Cyan
    & $bootstrap

    $vcpkgExe = Join-Path $RootPath "vcpkg.exe"
    if (-not (Test-Path $vcpkgExe)) {
        throw "vcpkg.exe nao encontrado apos bootstrap."
    }

    Write-Host "Integrando vcpkg..." -ForegroundColor Cyan
    & $vcpkgExe integrate install

    Write-Host "Instalando libs C++ (cppzmq, nlohmann-json)..." -ForegroundColor Cyan
    & $vcpkgExe install cppzmq nlohmann-json

    Write-Host "Definindo VCPKG_ROOT..." -ForegroundColor Cyan
    setx VCPKG_ROOT $RootPath | Out-Null
    $env:VCPKG_ROOT = $RootPath
}

# Root do repositorio (onde este script esta)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Repo root: $root" -ForegroundColor Gray

# Pre-checagens
Ensure-Command -Name "git" -InstallHint "Instale o Git e tente novamente."
Ensure-Command -Name "python" -InstallHint "Instale Python 3.10+ (com pip no PATH)."
Ensure-Command -Name "pip" -InstallHint "Garanta que pip esta disponivel no PATH."
Ensure-Command -Name "node" -InstallHint "Instale Node.js 20+."
Ensure-Command -Name "npm" -InstallHint "Instale Node.js com npm."
Ensure-Command -Name "cmake" -InstallHint "Instale CMake 3.25+."
Ensure-Command -Name "cargo" -InstallHint "Instale Rust (rustup)."

# vcpkg
Ensure-Vcpkg

# NPM - frontend
Write-Host "Instalando dependencias do frontend..." -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
npm install
Pop-Location

# NPM - app (Tauri)
Write-Host "Instalando dependencias do app (Tauri)..." -ForegroundColor Cyan
Push-Location (Join-Path $root "app")
npm install
Pop-Location

# Python - distributor
Write-Host "Instalando dependencias Python do distributor..." -ForegroundColor Cyan
Push-Location (Join-Path $root "distributor")
python -m pip install --upgrade pip
pip install -r requirements.txt
if (Test-Path "requirements_ocr.txt") {
    pip install -r requirements_ocr.txt
}
Pop-Location

# Python - sync_monitor
if (Test-Path (Join-Path $root "sync_monitor\requirements.txt")) {
    Write-Host "Instalando dependencias Python do sync_monitor..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "sync_monitor")
    pip install -r requirements.txt
    Pop-Location
}

# Dependencias opcionais para build do instalador
if ($IncludeInstallerDeps) {
    Write-Host "Instalando dependencias opcionais do instalador (PyInstaller)..." -ForegroundColor Cyan
    pip install pyinstaller
}

# Teste de configure/build da engine
Write-Host "Configurando engine (CMake)..." -ForegroundColor Cyan
Push-Location (Join-Path $root "engine")
cmake -B build -DCMAKE_TOOLCHAIN_FILE="$env:VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"
cmake --build build --config Release
Pop-Location

Write-Host ""
Write-Host "Setup concluido com sucesso." -ForegroundColor Green
Write-Host "Proximo passo: .\scripts\run-dev.ps1" -ForegroundColor Green
