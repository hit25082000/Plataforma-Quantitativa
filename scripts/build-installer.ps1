# Build completo para o instalador M5 - Plataforma Quantitativa
# Requer: Rust, Node.js, Python, CMake, MSVC, PyInstaller

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$buildLog = Join-Path $logsDir "installer-build-$ts.log"
$phaseStart = @{}
$phaseResults = @()
Start-Transcript -Path $buildLog -Append | Out-Null

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    $started = Get-Date
    $phaseStart[$Name] = $started
    Write-Host ("`n=== {0} ===" -f $Name) -ForegroundColor Cyan
    Write-Host ("[build-installer] step_start name={0} ts={1:o}" -f $Name, $started)
    try {
        & $Action
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        $phaseResults += [pscustomobject]@{
            step = $Name
            status = "ok"
            elapsed_s = $elapsed
        }
        Write-Host ("[build-installer] step_ok name={0} elapsed_s={1}" -f $Name, $elapsed)
    } catch {
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        $phaseResults += [pscustomobject]@{
            step = $Name
            status = "failed"
            elapsed_s = $elapsed
        }
        Write-Host ("[build-installer] step_failed name={0} elapsed_s={1} error={2}" -f $Name, $elapsed, $_.Exception.Message) -ForegroundColor Red
        throw
    }
}

# Garantir PATH com ferramentas de build
$env:Path = "C:\Program Files\CMake\bin;$env:USERPROFILE\.cargo\bin;$env:APPDATA\Python\Python313\Scripts;$env:LOCALAPPDATA\Programs\Python\Python313\Scripts;" + $env:Path
if (Test-Path "C:\vcpkg") { $env:VCPKG_ROOT = "C:\vcpkg" }

$cmake = if (Get-Command cmake -ErrorAction SilentlyContinue) { "cmake" } else { "C:\Program Files\CMake\bin\cmake.exe" }
try {
    Invoke-Step -Name "1. Build Engine" -Action {
        Push-Location "$root\engine"
        try {
            if (-not (Test-Path "build\CMakeCache.txt")) {
                if (-not (Test-Path "build")) { New-Item -ItemType Directory -Path build | Out-Null }
                $vcpkgToolchain = if ($env:VCPKG_ROOT) { "-DCMAKE_TOOLCHAIN_FILE=$env:VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" } else { "" }
                & $cmake -B build -S . $vcpkgToolchain
            }
            & $cmake --build build --config Release
            if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar engine (exit=$LASTEXITCODE)." }
        } finally {
            Pop-Location
        }
    }

    Invoke-Step -Name "2. Build Distributor" -Action {
        Push-Location "$root\distributor"
        try {
            pip install pyinstaller -q
            python -m PyInstaller distributor.spec --noconfirm
            if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar distributor.exe (exit=$LASTEXITCODE)." }
            python -m PyInstaller profit_ocr_service.spec --noconfirm
            if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar profit_ocr_service.exe (exit=$LASTEXITCODE)." }
        } finally {
            Pop-Location
        }
    }

    Invoke-Step -Name "3. Copiar recursos para app" -Action {
        $resources = "$root\app\src-tauri\resources"
        New-Item -ItemType Directory -Force -Path $resources | Out-Null
        New-Item -ItemType Directory -Force -Path "$resources\sounds" | Out-Null

        & "$root\scripts\sync-profit-ocr-to-tauri-resources.ps1" -RepoRoot $root

        Copy-Item "$root\engine\build\Release\engine.exe" "$resources\" -Force
        Copy-Item "$root\ProfitDLL.dll" "$resources\" -Force -ErrorAction SilentlyContinue
        # 64-bit DLL: engine tries ProfitDLL64.dll first (fallback to ProfitDLL.dll)
        if (Test-Path "$root\ProfitDLL64.dll") {
            Copy-Item "$root\ProfitDLL64.dll" "$resources\" -Force
        } elseif (Test-Path "$root\engine\build\Release\ProfitDLL64.dll") {
            Copy-Item "$root\engine\build\Release\ProfitDLL64.dll" "$resources\" -Force
        }
        Copy-Item "$root\engine\build\Release\libzmq-mt-4_3_5.dll" "$resources\" -Force -ErrorAction SilentlyContinue
        Copy-Item "$root\distributor\dist\distributor.exe" "$resources\" -Force
        Copy-Item "$root\distributor\dist\profit_ocr_service.exe" "$resources\" -Force

        if (-not (Test-Path "$resources\ProfitDLL64.dll")) {
            throw "ProfitDLL64.dll nao encontrado na raiz nem em engine\build\Release. Coloque ProfitDLL64.dll na raiz (ver README)."
        }
        # Tauri lista ProfitDLL.dll no bundle; se só existir 64 bits, duplicar nome (engine aceita fallback)
        if (-not (Test-Path "$resources\ProfitDLL.dll") -and (Test-Path "$resources\ProfitDLL64.dll")) {
            Copy-Item "$resources\ProfitDLL64.dll" "$resources\ProfitDLL.dll" -Force
        }

        # Sons - preferir frontend/public/sounds se existir; senão installer-resources
        if (Test-Path "$root\frontend\public\sounds") {
            Copy-Item "$root\frontend\public\sounds\*" "$resources\sounds\" -Force -ErrorAction SilentlyContinue
        }
        $soundsSrc = "$root\installer-resources\sounds"
        if (-not (Test-Path "$soundsSrc\wall.wav")) {
            & "$root\installer-resources\sounds\create-placeholder-wav.ps1"
        }
        Copy-Item "$soundsSrc\wall.wav" "$resources\sounds\" -Force -ErrorAction SilentlyContinue
        Copy-Item "$soundsSrc\breakout.wav" "$resources\sounds\" -Force -ErrorAction SilentlyContinue
    }

    Invoke-Step -Name "4. Build Tauri App" -Action {
        Push-Location "$root\frontend"
        try {
            npm ci 2>$null
            if ($LASTEXITCODE -ne 0) {
                npm install -q
                if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências do frontend." }
            }
        } finally {
            Pop-Location
        }
        Push-Location "$root\app"
        try {
            npm ci 2>$null
            if ($LASTEXITCODE -ne 0) {
                npm install -q
                if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências do app." }
            }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "Falha no build Tauri." }
        } finally {
            Pop-Location
        }
    }

    Write-Host "`n=== Concluído ===" -ForegroundColor Green
    $bundle = Get-ChildItem -Path "$root\app\src-tauri\target\release\bundle" -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($bundle) {
        Write-Host "Instalador: $($bundle.FullName)" -ForegroundColor Yellow
    }
} catch {
    Write-Host ("`n[build-installer] erro: {0}" -f $_.Exception.Message) -ForegroundColor Red
    throw
} finally {
    Write-Host "`nResumo de etapas:" -ForegroundColor Cyan
    foreach ($r in $phaseResults) {
        Write-Host (" - {0}: {1} ({2}s)" -f $r.step, $r.status, $r.elapsed_s)
    }
    Write-Host ("Log completo: {0}" -f $buildLog) -ForegroundColor Yellow
    Stop-Transcript | Out-Null
}
