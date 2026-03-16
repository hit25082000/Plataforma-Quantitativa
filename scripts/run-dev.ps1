# Run full stack: build engine, then start Tauri (which manages engine + distributor).
# Credentials are read from the app config by Tauri and passed to the engine process.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Kill-StaleProcesses {
    $staleEngines = Get-Process -Name "engine" -ErrorAction SilentlyContinue
    if ($staleEngines) {
        Write-Host "Matando $($staleEngines.Count) processo(s) engine.exe residual(is)..." -ForegroundColor Yellow
        $staleEngines | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }

    $netstat = netstat -ano 2>$null | Select-String ":8000\s" | Select-String "LISTENING"
    foreach ($line in $netstat) {
        if ($line -match '\s(\d+)$') {
            $procId = [int]$Matches[1]
            Write-Host "Matando processo na porta 8000 (PID $procId)..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }

    $netstat5555 = netstat -ano 2>$null | Select-String ":5555\s" | Select-String "LISTENING"
    foreach ($line in $netstat5555) {
        if ($line -match '\s(\d+)$') {
            $procId = [int]$Matches[1]
            Write-Host "Matando processo na porta 5555 (PID $procId)..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }

    $netstat5557 = netstat -ano 2>$null | Select-String ":5557\s" | Select-String "LISTENING"
    foreach ($line in $netstat5557) {
        if ($line -match '\s(\d+)$') {
            $procId = [int]$Matches[1]
            Write-Host "Matando processo na porta 5557 (sync_monitor, PID $procId)..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

$syncMonitorProcess = $null
$distributorProcess = $null
try {
    Kill-StaleProcesses

    $engineDir = Join-Path $root "engine\build\Release"
    $engineExe = Join-Path $engineDir "engine.exe"

    # Build engine
    Write-Host "=== Construindo engine ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root "engine")
    cmake -B build 2>&1 | Out-Null
    cmake --build build --config Release 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build Release falhou, tentando Debug..." -ForegroundColor Yellow
        cmake --build build --config Debug 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $engineDir = Join-Path $root "engine\build\Debug"
            $engineExe = Join-Path $engineDir "engine.exe"
        }
    }
    Pop-Location

    if (-not (Test-Path $engineExe)) {
        Write-Host "engine.exe nao encontrado em: $engineDir" -ForegroundColor Red
        Write-Host "Feche processos que usam engine.exe e rode novamente." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Engine compilado: $engineExe" -ForegroundColor Green

    # Copy DLLs to engine build dir
    $dll64 = Join-Path $root "ProfitDLL64.dll"
    $dll32 = Join-Path $root "ProfitDLL.dll"
    if (Test-Path $dll64) {
        Copy-Item $dll64 $engineDir -Force
        Write-Host "ProfitDLL64.dll copiada para $engineDir" -ForegroundColor Gray
    }
    if (Test-Path $dll32) {
        Copy-Item $dll32 $engineDir -Force
        Write-Host "ProfitDLL.dll copiada para $engineDir" -ForegroundColor Gray
    }

    # Copy engine + distributor to Tauri resources so spawn_engine/spawn_distributor find them
    $tauriResources = Join-Path $root "app\src-tauri\resources"
    if (Test-Path $tauriResources) {
        Copy-Item $engineExe (Join-Path $tauriResources "engine.exe") -Force
        Write-Host "engine.exe copiado para $tauriResources" -ForegroundColor Gray

        # Copy DLLs needed by engine
        foreach ($dll in @("ProfitDLL64.dll", "ProfitDLL.dll", "libzmq-mt-4_3_5.dll")) {
            $src = Join-Path $engineDir $dll
            if (Test-Path $src) {
                Copy-Item $src $tauriResources -Force
            }
        }
    }

    # Install distributor dependencies
    Write-Host "=== Instalando dependencias do distributor (se necessario) ===" -ForegroundColor Cyan
    $distDir = Join-Path $root "distributor"
    Push-Location $distDir
    pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    Pop-Location

    # Start distributor (Python) so WS :8000 is up when Vite/Tauri load (evita ECONNREFUSED no proxy)
    Write-Host "=== Iniciando distributor (em background) ===" -ForegroundColor Cyan
    $distributorProcess = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $distDir -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 1200

    # Install and start sync_monitor (hidden, no terminal)
    $syncMonitorDir = Join-Path $root "sync_monitor"
    if (Test-Path (Join-Path $syncMonitorDir "main.py")) {
        Write-Host "=== Instalando e iniciando sync_monitor (em background) ===" -ForegroundColor Cyan
        Push-Location $syncMonitorDir
        $prevErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        pip install -r requirements.txt -q 2>&1 | Out-Null
        $ErrorActionPreference = $prevErrorAction
        $syncMonitorProcess = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $syncMonitorDir -WindowStyle Hidden -PassThru
        Pop-Location
        Start-Sleep -Milliseconds 800
    }

    # Start Tauri app (Tauri manages engine; distributor e sync_monitor ja rodando em background)
    Write-Host "=== Iniciando app Tauri ===" -ForegroundColor Cyan
    Write-Host "Distributor e sync_monitor ja em background. Inicie o engine pelas Configuracoes." -ForegroundColor Gray
    Push-Location (Join-Path $root "app")
    npm run dev
    $exitCode = $LASTEXITCODE
    Pop-Location
    exit $exitCode
} finally {
    if ($distributorProcess -and -not $distributorProcess.HasExited) {
        Stop-Process -Id $distributorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($syncMonitorProcess -and -not $syncMonitorProcess.HasExited) {
        Stop-Process -Id $syncMonitorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Kill-StaleProcesses
}
