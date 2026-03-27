# Build Installer Script for Plataforma Quantitativa
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$EngineDir = Join-Path $ProjectRoot "engine"
$DistributorDir = Join-Path $ProjectRoot "distributor"
$AppDir = Join-Path $ProjectRoot "app"
$ResourcesDir = Join-Path $AppDir "src-tauri\resources"

$env:Path = "C:\Program Files\CMake\bin;$env:USERPROFILE\.cargo\bin;$env:APPDATA\Python\Python313\Scripts;$env:LOCALAPPDATA\Programs\Python\Python313\Scripts;" + $env:Path
if (Test-Path "C:\vcpkg") { $env:VCPKG_ROOT = "C:\vcpkg" }
$cmake = if (Get-Command cmake -ErrorAction SilentlyContinue) { "cmake" } else { "C:\Program Files\CMake\bin\cmake.exe" }

Write-Host "--- Starting Installer Build Process ---" -ForegroundColor Cyan

# 1. Build Engine (C++)
Write-Host "Building C++ Engine (Release)..." -ForegroundColor Yellow
$engineBuild = Join-Path $EngineDir "build"
if (-not (Test-Path (Join-Path $engineBuild "CMakeCache.txt"))) {
    if (-not (Test-Path $engineBuild)) { New-Item -ItemType Directory -Path $engineBuild | Out-Null }
    if ($env:VCPKG_ROOT) {
        & $cmake -B $engineBuild -S $EngineDir "-DCMAKE_TOOLCHAIN_FILE=$env:VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"
    }
    else {
        & $cmake -B $engineBuild -S $EngineDir
    }
    if ($LASTEXITCODE -ne 0) { Write-Error "CMake configure failed"; exit 1 }
}
& $cmake --build $engineBuild --config Release
if ($LASTEXITCODE -ne 0) { Write-Error "Engine build failed"; exit 1 }

$releaseDir = Join-Path $engineBuild "Release"

# 2. Build Distributor (Python)
Write-Host "Building Python Distributor..." -ForegroundColor Yellow
Push-Location $DistributorDir
try {
    pip install pyinstaller --quiet
    python -m PyInstaller distributor.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { Write-Error "Distributor build failed"; exit 1 }
}
finally { Pop-Location }

# 3. Prepare Resources
Write-Host "Preparing Resources for Tauri..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $ResourcesDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ResourcesDir "sounds") | Out-Null

Copy-Item (Join-Path $releaseDir "engine.exe") (Join-Path $ResourcesDir "engine.exe") -Force
Get-ChildItem -Path $releaseDir -Filter "libzmq-mt*.dll" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName $ResourcesDir -Force
}
Copy-Item (Join-Path $DistributorDir "dist\distributor.exe") (Join-Path $ResourcesDir "distributor.exe") -Force

Copy-Item (Join-Path $ProjectRoot "ProfitDLL.dll") (Join-Path $ResourcesDir "ProfitDLL.dll") -Force -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $ProjectRoot "ProfitDLL64.dll")) {
    Copy-Item (Join-Path $ProjectRoot "ProfitDLL64.dll") (Join-Path $ResourcesDir "ProfitDLL64.dll") -Force
}
elseif (Test-Path (Join-Path $releaseDir "ProfitDLL64.dll")) {
    Copy-Item (Join-Path $releaseDir "ProfitDLL64.dll") (Join-Path $ResourcesDir "ProfitDLL64.dll") -Force
}
if (-not (Test-Path (Join-Path $ResourcesDir "ProfitDLL64.dll"))) {
    Write-Error "ProfitDLL64.dll nao encontrado na raiz do repo, em engine/build/Release nem em resources. Coloque ProfitDLL64.dll na raiz (ver README)."
    exit 1
}
# Tauri exige resources/ProfitDLL.dll no manifesto; se só houver 64 bits, duplicar nome (fallback do engine aceita)
if (-not (Test-Path (Join-Path $ResourcesDir "ProfitDLL.dll"))) {
    Copy-Item (Join-Path $ResourcesDir "ProfitDLL64.dll") (Join-Path $ResourcesDir "ProfitDLL.dll") -Force
}

$soundsInstaller = Join-Path $ProjectRoot "installer-resources\sounds"
if (Test-Path (Join-Path $ProjectRoot "frontend\public\sounds")) {
    Copy-Item (Join-Path $ProjectRoot "frontend\public\sounds\*") (Join-Path $ResourcesDir "sounds\") -Force
}
if ((-not (Test-Path (Join-Path $ResourcesDir "sounds\wall.wav"))) -and (Test-Path $soundsInstaller)) {
    if (-not (Test-Path (Join-Path $soundsInstaller "wall.wav"))) {
        $ph = Join-Path $soundsInstaller "create-placeholder-wav.ps1"
        if (Test-Path $ph) { & $ph }
    }
    Copy-Item (Join-Path $soundsInstaller "wall.wav") (Join-Path $ResourcesDir "sounds\") -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $soundsInstaller "breakout.wav") (Join-Path $ResourcesDir "sounds\") -Force -ErrorAction SilentlyContinue
}

# 4. Build Tauri Bundle (frontend + NSIS via beforeBuildCommand)
Write-Host "Building Tauri Bundle (NSIS Installer)..." -ForegroundColor Yellow
Push-Location $AppDir
try {
    npm install
    if ($LASTEXITCODE -ne 0) { Write-Error "npm install failed"; exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Error "Tauri build failed"; exit 1 }
}
finally { Pop-Location }

Write-Host "--- Build Process Completed Successfully ---" -ForegroundColor Green
$setup = Get-ChildItem -Path (Join-Path $AppDir "src-tauri\target\release\bundle\nsis") -Filter "*setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($setup) {
    Write-Host "Instalador: $($setup.FullName)" -ForegroundColor Yellow
}
Set-Location $ProjectRoot
