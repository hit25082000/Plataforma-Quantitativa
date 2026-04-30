# Run full stack: build engine, then start Tauri (which manages engine + distributor).
# Portas canónicas: ver ../../docs/PORTS.md
# Credentials are read from the app config by Tauri and passed to the engine process.
#
# Parâmetros:
#   -StartOcr  Inicia profit_ocr_service.py em background (porta PQ_OCR_PORT ou 5558).
#              Por defeito NÃO inicia o OCR: o Tauri faz spawn ao abrir o overlay.

param(
    [switch]$StartOcr
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Load-DotEnvFiles {
    $dotenvFiles = @(
        (Join-Path $root ".env"),
        (Join-Path $root ".env.local")
    )

    $loadedKeys = @()
    foreach ($dotenvPath in $dotenvFiles) {
        if (-not (Test-Path $dotenvPath)) {
            continue
        }
        Get-Content $dotenvPath | ForEach-Object {
            $line = $_.Trim()
            if (-not $line -or $line.StartsWith("#")) {
                return
            }
            if ($line -notmatch '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
                return
            }
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $commentIdx = $value.IndexOf(" #")
            if ($commentIdx -ge 0) {
                $value = $value.Substring(0, $commentIdx)
            }
            $value = $value.Trim()

            $currentValue = [Environment]::GetEnvironmentVariable($key, "Process")
            if (-not [string]::IsNullOrWhiteSpace($currentValue)) {
                return
            }
            Set-Item -Path ("env:" + $key) -Value $value
            $loadedKeys += $key
        }
    }

    $loadedKeys = @($loadedKeys | Select-Object -Unique)
    if ($loadedKeys.Count -gt 0) {
        Write-Host ("Variaveis carregadas do .env: " + ($loadedKeys -join ", ")) -ForegroundColor Gray
    }
}

function Apply-ProfitEnvAliases {
    $aliasPairs = @(
        @{ Target = "PROFIT_ACTIVATION_KEY"; Source = "DLL_KEY" },
        @{ Target = "PROFIT_ACTIVATION_KEY"; Source = "PROFIT_DLL_ACTIVATION_KEY" },
        @{ Target = "PROFIT_DLL_ACTIVATION_KEY"; Source = "PROFIT_ACTIVATION_KEY" },
        @{ Target = "PROFIT_USER"; Source = "PROFIT_DLL_USER" },
        @{ Target = "PROFIT_DLL_USER"; Source = "PROFIT_USER" },
        @{ Target = "PROFIT_PASSWORD"; Source = "PROFIT_DLL_PASSWORD" },
        @{ Target = "PROFIT_DLL_PASSWORD"; Source = "PROFIT_PASSWORD" }
    )

    $applied = @()
    foreach ($pair in $aliasPairs) {
        $targetValue = [Environment]::GetEnvironmentVariable($pair.Target, "Process")
        if (-not [string]::IsNullOrWhiteSpace($targetValue)) {
            continue
        }
        $sourceValue = [Environment]::GetEnvironmentVariable($pair.Source, "Process")
        if ([string]::IsNullOrWhiteSpace($sourceValue)) {
            continue
        }
        Set-Item -Path ("env:" + $pair.Target) -Value $sourceValue
        $applied += ($pair.Source + "->" + $pair.Target)
    }

    if ($applied.Count -gt 0) {
        Write-Host ("Aliases aplicados: " + ($applied -join ", ")) -ForegroundColor Gray
    }
}

function Kill-ListenersOnPort {
    param(
        [int]$Port,
        [string]$Label
    )
    $pattern = ":$Port\s"
    $netstat = netstat -ano 2>$null | Select-String $pattern | Select-String "LISTENING"
    foreach ($line in $netstat) {
        if ($line -match '\s(\d+)$') {
            $procId = [int]$Matches[1]
            Write-Host "Matando processo na porta $Port ($Label, PID $procId)..." -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Kill-StaleProcesses {
    $staleEngines = Get-Process -Name "engine" -ErrorAction SilentlyContinue
    if ($staleEngines) {
        Write-Host "Matando $($staleEngines.Count) processo(s) engine.exe residual(is)..." -ForegroundColor Yellow
        $staleEngines | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }

    $ocrKillPort = 5558
    if ($null -ne $env:PQ_OCR_PORT -and $env:PQ_OCR_PORT -ne "") {
        $parsed = 0
        if ([int]::TryParse($env:PQ_OCR_PORT, [ref]$parsed)) {
            $ocrKillPort = $parsed
        }
    }

    Kill-ListenersOnPort -Port 8000 -Label "distributor HTTP/WS"
    Kill-ListenersOnPort -Port 5555 -Label "ZMQ engine (mercado)"
    Kill-ListenersOnPort -Port 5556 -Label "TCP engine SWITCH / troca de ativo"
    Kill-ListenersOnPort -Port 5557 -Label "ZMQ sync_monitor"
    Kill-ListenersOnPort -Port $ocrKillPort -Label "OCR overlay HTTP/WS"
}

function Load-KmsSecretsIfEnabled {
    $enabledRaw = if ($env:AWS_KMS_ENABLED) { $env:AWS_KMS_ENABLED } else { $env:KMS_ENABLED }
    if (-not $enabledRaw) {
        return
    }
    $enabledNorm = $enabledRaw.Trim().ToLowerInvariant()
    if ($enabledNorm -notin @("1", "true", "yes", "on", "sim")) {
        return
    }

    $loader = Join-Path $root "scripts\load_kms_secrets.py"
    if (-not (Test-Path $loader)) {
        throw "AWS_KMS_ENABLED=1, mas loader não encontrado: $loader"
    }

    Write-Host "=== Carregando segredos AWS KMS ===" -ForegroundColor Cyan
    $json = & python $loader --json-values
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao carregar segredos via KMS."
    }
    if (-not $json) {
        return
    }
    $loaded = $json | ConvertFrom-Json
    foreach ($prop in $loaded.PSObject.Properties) {
        Set-Item -Path ("env:" + $prop.Name) -Value ([string]$prop.Value)
    }
    $loadedNames = @($loaded.PSObject.Properties | ForEach-Object { $_.Name })
    if ($loadedNames.Count -gt 0) {
        Write-Host ("Segredos carregados: " + ($loadedNames -join ", ")) -ForegroundColor Gray
    }
}

$syncMonitorProcess = $null
$distributorProcess = $null
$ocrProcess = $null
try {
    Kill-StaleProcesses
    Load-DotEnvFiles
    Load-KmsSecretsIfEnabled
    Apply-ProfitEnvAliases

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

        & (Join-Path $root "scripts\sync-profit-ocr-to-tauri-resources.ps1") -RepoRoot $root
    }

    # Install distributor dependencies
    Write-Host "=== Instalando dependencias do distributor (se necessario) ===" -ForegroundColor Cyan
    $distDir = Join-Path $root "distributor"
    Push-Location $distDir
    pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    if (Test-Path (Join-Path $distDir "requirements_ocr.txt")) {
        pip install -r requirements_ocr.txt -q
        if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    }
    Pop-Location

    # Start distributor (Python) so WS :8000 is up when Vite/Tauri load (evita ECONNREFUSED no proxy)
    Write-Host "=== Iniciando distributor (em background) ===" -ForegroundColor Cyan
    $distributorProcess = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $distDir -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 1200

    if ($StartOcr) {
        $ocrScript = Join-Path $distDir "profit_ocr_service.py"
        if (Test-Path $ocrScript) {
            Write-Host "=== Iniciando OCR overlay service (-StartOcr; porta PQ_OCR_PORT ou 5558) ===" -ForegroundColor Cyan
            $prevTesseractCmd = $env:TESSERACT_CMD
            $env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
            $ocrProcess = Start-Process -FilePath "python" -ArgumentList "profit_ocr_service.py" -WorkingDirectory $distDir -WindowStyle Hidden -PassThru
            $env:TESSERACT_CMD = $prevTesseractCmd
            Start-Sleep -Milliseconds 800
        } else {
            Write-Host "OCR service nao encontrado: $ocrScript" -ForegroundColor Yellow
        }
    } else {
        Write-Host "OCR nao iniciado pelo script (use -StartOcr se precisar). O app Tauri sobe o OCR ao abrir o overlay." -ForegroundColor Gray
    }

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
    npm run dev:tauri
    $exitCode = $LASTEXITCODE
    Pop-Location
    exit $exitCode
} finally {
    if ($ocrProcess -and -not $ocrProcess.HasExited) {
        Stop-Process -Id $ocrProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($distributorProcess -and -not $distributorProcess.HasExited) {
        Stop-Process -Id $distributorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($syncMonitorProcess -and -not $syncMonitorProcess.HasExited) {
        Stop-Process -Id $syncMonitorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Kill-StaleProcesses
}
