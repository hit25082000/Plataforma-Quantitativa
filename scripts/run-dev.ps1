# Run full stack: engine + distributor + Tauri app.
# Set PROFIT_* env vars before running, or the engine may fail.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$engineProc = $null
$distProc = $null

function Stop-BackgroundProcesses {
    if ($engineProc -and -not $engineProc.HasExited) {
        Stop-Process -Id $engineProc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "Engine encerrado." -ForegroundColor Yellow
    }
    if ($distProc -and -not $distProc.HasExited) {
        Stop-Process -Id $distProc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "Distributor encerrado." -ForegroundColor Yellow
    }
}

function Kill-StaleProcesses {
    # Kill any leftover engine.exe or distributor python processes from previous runs
    $staleEngines = Get-Process -Name "engine" -ErrorAction SilentlyContinue
    if ($staleEngines) {
        Write-Host "Matando $($staleEngines.Count) processo(s) engine.exe residual(is)..." -ForegroundColor Yellow
        $staleEngines | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }

    # Kill python processes running distributor main.py (listening on port 8000)
    $netstat = netstat -ano 2>$null | Select-String ":8000\s" | Select-String "LISTENING"
    foreach ($line in $netstat) {
        if ($line -match '\s(\d+)$') {
            $pid = [int]$Matches[1]
            Write-Host "Matando processo na porta 8000 (PID $pid)..." -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }

    # Also check port 5555 (ZMQ)
    $netstat5555 = netstat -ano 2>$null | Select-String ":5555\s" | Select-String "LISTENING"
    foreach ($line in $netstat5555) {
        if ($line -match '\s(\d+)$') {
            $pid = [int]$Matches[1]
            Write-Host "Matando processo na porta 5555 (PID $pid)..." -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
    # Clean up stale processes FIRST
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
    Write-Host "Engine: $engineExe" -ForegroundColor Gray

    # DLL: 64-bit build uses ProfitDLL64.dll; script copies whichever exists
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

    Write-Host "=== Iniciando engine ===" -ForegroundColor Cyan
    if (-not $env:PROFIT_ACTIVATION_KEY -or -not $env:PROFIT_USER -or -not $env:PROFIT_PASSWORD) {
        Write-Host "AVISO: Defina PROFIT_ACTIVATION_KEY, PROFIT_USER e PROFIT_PASSWORD no terminal para a engine conectar ao Profit." -ForegroundColor Yellow
    }
    $engineProc = Start-Process -FilePath $engineExe -WorkingDirectory $engineDir -PassThru
    Write-Host "Engine PID: $($engineProc.Id)" -ForegroundColor Gray

    # Give engine time to bind ZMQ port before starting distributor
    Write-Host "Aguardando engine iniciar (2s)..." -ForegroundColor Gray
    Start-Sleep -Seconds 2

    # Check if engine is still running (exits immediately if ZMQ bind fails)
    if ($engineProc.HasExited) {
        Write-Host "ERRO: Engine saiu imediatamente (exit code: $($engineProc.ExitCode)). Verifique se a porta 5555 esta livre." -ForegroundColor Red
        exit 1
    }

    Write-Host "=== Instalando dependencias do distributor (se necessario) ===" -ForegroundColor Cyan
    $distDir = Join-Path $root "distributor"
    Push-Location $distDir
    pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    Pop-Location

    Write-Host "=== Iniciando distributor ===" -ForegroundColor Cyan
    $distProc = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $distDir -PassThru -NoNewWindow
    Write-Host "Distributor PID: $($distProc.Id)" -ForegroundColor Gray

    Write-Host "=== Aguardando distributor (3s) ===" -ForegroundColor Cyan
    Start-Sleep -Seconds 3

    Write-Host "=== Iniciando app Tauri ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root "app")
    npm run dev
    $exitCode = $LASTEXITCODE
    Pop-Location
    exit $exitCode
} finally {
    Stop-BackgroundProcesses
}
