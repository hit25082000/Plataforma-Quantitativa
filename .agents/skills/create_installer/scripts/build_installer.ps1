# Build Installer Script for Plataforma Quantitativa

$ProjectRoot = Get-Location
$EngineDir = "$ProjectRoot/engine"
$DistributorDir = "$ProjectRoot/distributor"
$AppDir = "$ProjectRoot/app"
$ResourcesDir = "$AppDir/src-tauri/resources"

Write-Host "--- Starting Installer Build Process ---" -ForegroundColor Cyan

# 1. Build Engine (C++)
Write-Host "Building C++ Engine (Release)..." -ForegroundColor Yellow
Set-Location "$EngineDir/build"
cmake --build . --config Release
if ($LASTEXITCODE -ne 0) { Write-Error "Engine build failed"; exit 1 }

# 2. Build Distributor (Python)
Write-Host "Building Python Distributor..." -ForegroundColor Yellow
Set-Location $DistributorDir
# Ensure PyInstaller
pip install pyinstaller --quiet
python -m PyInstaller distributor.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Error "Distributor build failed"; exit 1 }

# 3. Prepare Resources
Write-Host "Preparing Resources for Tauri..." -ForegroundColor Yellow
if (!(Test-Path $ResourcesDir)) { New-Item -ItemType Directory -Path $ResourcesDir -Force }
if (!(Test-Path "$ResourcesDir/sounds")) { New-Item -ItemType Directory -Path "$ResourcesDir/sounds" -Force }

Copy-Item "$EngineDir/build/Release/engine.exe" "$ResourcesDir/engine.exe" -Force
Copy-Item "$EngineDir/build/Release/libzmq-mt*.dll" "$ResourcesDir" -Force
Copy-Item "$DistributorDir/dist/distributor.exe" "$ResourcesDir/distributor.exe" -Force
Copy-Item "$ProjectRoot/ProfitDLL.dll" "$ResourcesDir/ProfitDLL.dll" -Force
if (Test-Path "$ProjectRoot/frontend/public/sounds") {
    Copy-Item "$ProjectRoot/frontend/public/sounds/*" "$ResourcesDir/sounds/" -Force
}

# 4. Build Tauri Bundle
Write-Host "Building Tauri Bundle (NSIS Installer)..." -ForegroundColor Yellow
Set-Location $AppDir
npm install
npm run tauri build

Write-Host "--- Build Process Completed Successfully ---" -ForegroundColor Green
Set-Location $ProjectRoot
