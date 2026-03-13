# Build completo para o instalador M5 - Plataforma Quantitativa
# Requer: Rust, Node.js, Python, CMake, MSVC, PyInstaller

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Garantir PATH com ferramentas de build
$env:Path = "C:\Program Files\CMake\bin;$env:USERPROFILE\.cargo\bin;$env:APPDATA\Python\Python313\Scripts;$env:LOCALAPPDATA\Programs\Python\Python313\Scripts;" + $env:Path
if (Test-Path "C:\vcpkg") { $env:VCPKG_ROOT = "C:\vcpkg" }

$cmake = if (Get-Command cmake -ErrorAction SilentlyContinue) { "cmake" } else { "C:\Program Files\CMake\bin\cmake.exe" }

Write-Host "=== 1. Build Engine ===" -ForegroundColor Cyan
Push-Location "$root\engine"
if (-not (Test-Path "build\CMakeCache.txt")) {
    if (-not (Test-Path "build")) { New-Item -ItemType Directory -Path build | Out-Null }
    $vcpkgToolchain = if ($env:VCPKG_ROOT) { "-DCMAKE_TOOLCHAIN_FILE=$env:VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" } else { "" }
    & $cmake -B build -S . $vcpkgToolchain
}
& $cmake --build build --config Release
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Write-Host "`n=== 2. Build Distributor ===" -ForegroundColor Cyan
Push-Location "$root\distributor"
pip install pyinstaller -q
python -m PyInstaller distributor.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Write-Host "`n=== 3. Copiar recursos para app ===" -ForegroundColor Cyan
$resources = "$root\app\src-tauri\resources"
New-Item -ItemType Directory -Force -Path $resources | Out-Null
New-Item -ItemType Directory -Force -Path "$resources\sounds" | Out-Null

Copy-Item "$root\engine\build\Release\engine.exe" "$resources\" -Force
Copy-Item "$root\ProfitDLL.dll" "$resources\" -Force
Copy-Item "$root\distributor\dist\distributor.exe" "$resources\" -Force

# Sons - criar placeholders se não existirem, depois copiar
$soundsSrc = "$root\installer-resources\sounds"
if (-not (Test-Path "$soundsSrc\wall.wav")) {
    & "$root\installer-resources\sounds\create-placeholder-wav.ps1"
}
Copy-Item "$soundsSrc\wall.wav" "$resources\sounds\" -Force -ErrorAction SilentlyContinue
Copy-Item "$soundsSrc\breakout.wav" "$resources\sounds\" -Force -ErrorAction SilentlyContinue

Write-Host "`n=== 4. Build Tauri App ===" -ForegroundColor Cyan
Push-Location "$root\app"
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Write-Host "`n=== Concluído ===" -ForegroundColor Green
$bundle = Get-ChildItem -Path "$root\app\src-tauri\target\release\bundle" -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($bundle) {
    Write-Host "Instalador: $($bundle.FullName)" -ForegroundColor Yellow
}
