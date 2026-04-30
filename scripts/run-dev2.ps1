param(
    [switch]$RequireShmMapping,
    [int]$ShmProbeTimeoutSeconds = 8
)

# Run local SHM test: engine (SHM writer) + distributor (SHM consumer).

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

function Ensure-RagDefaults {
    if ([string]::IsNullOrWhiteSpace($env:RAG_ENABLED)) {
        $env:RAG_ENABLED = "1"
    }
    if ([string]::IsNullOrWhiteSpace($env:RAG_VIEWS_ENABLED)) {
        $env:RAG_VIEWS_ENABLED = "1"
    }
    if ([string]::IsNullOrWhiteSpace($env:RAG_VIEWS_BACKEND)) {
        $env:RAG_VIEWS_BACKEND = "sqlite"
    }
    if ([string]::IsNullOrWhiteSpace($env:RAG_WALL_MIN_QTY)) {
        $env:RAG_WALL_MIN_QTY = "100"
    }

    $rawSqlitePath = [string]$env:RAG_VIEWS_SQLITE_PATH
    if ([string]::IsNullOrWhiteSpace($rawSqlitePath)) {
        $env:RAG_VIEWS_SQLITE_PATH = Join-Path $root "distributor\\logs\\rag_views_pregao.sqlite3"
    } elseif (-not [System.IO.Path]::IsPathRooted($rawSqlitePath)) {
        $env:RAG_VIEWS_SQLITE_PATH = Join-Path $root $rawSqlitePath
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
        Start-Sleep -Milliseconds 300
    }
    Kill-ListenersOnPort -Port 8000 -Label "distributor HTTP/WS"
    Kill-ListenersOnPort -Port 5555 -Label "ZMQ engine (mercado)"
    Kill-ListenersOnPort -Port 5556 -Label "TCP engine SWITCH / troca de ativo"
    Kill-ListenersOnPort -Port 5557 -Label "ZMQ sync_monitor"
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

function Build-Engine {
    Write-Host "=== Construindo engine ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root "engine")
    cmake -B build 2>&1 | Out-Null
    cmake --build build --config Release 2>&1 | Out-Null
    $engineDir = Join-Path $root "engine\build\Release"
    $engineExe = Join-Path $engineDir "engine.exe"
    if (-not (Test-Path $engineExe)) {
        Write-Host "Build Release falhou ou engine.exe ausente. Tentando Debug..." -ForegroundColor Yellow
        cmake --build build --config Debug 2>&1 | Out-Null
        $engineDir = Join-Path $root "engine\build\Debug"
        $engineExe = Join-Path $engineDir "engine.exe"
    }
    Pop-Location

    if (-not (Test-Path $engineExe)) {
        throw "engine.exe não encontrado após build."
    }

    $dll64 = Join-Path $root "ProfitDLL64.dll"
    $dll32 = Join-Path $root "ProfitDLL.dll"
    if (Test-Path $dll64) { Copy-Item $dll64 $engineDir -Force }
    if (Test-Path $dll32) { Copy-Item $dll32 $engineDir -Force }

    return @{ Dir = $engineDir; Exe = $engineExe }
}

function Wait-ForSharedMemoryMapping {
    param(
        [string]$MappingName,
        [int]$SizeMb,
        [int]$TimeoutSeconds = 120
    )

    Write-Host "=== Aguardando mapping SHM ===" -ForegroundColor Cyan
    Write-Host "Mapping=$MappingName SizeMb=$SizeMb TimeoutSeconds=$TimeoutSeconds" -ForegroundColor Gray

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $pythonProbe = "import sys; from pathlib import Path; root = Path(r'$root'); dist_dir = root / 'distributor'; sys.path.insert(0, str(dist_dir)); from mmap_consumer import MmapConsumer; ok, reason = MmapConsumer.probe_mapping(r'$MappingName', $($SizeMb * 1024 * 1024)); print(f'{int(ok)} {reason}')"
        $probe = & python -c $pythonProbe 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe -match '^1\s') {
            Write-Host "SHM disponível: $probe" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Milliseconds 1000
    }

    Write-Host "SHM não ficou disponível dentro do timeout." -ForegroundColor Red
    return $false
}

$engineProcess = $null
$distProcess = $null
try {
    Kill-StaleProcesses
    Load-DotEnvFiles
    Load-KmsSecretsIfEnabled
    Apply-ProfitEnvAliases
    Ensure-RagDefaults
    $built = Build-Engine
    $engineDir = $built.Dir
    $engineExe = $built.Exe
    $distDir = Join-Path $root "distributor"

    Write-Host "=== Instalando dependencias do distributor (se necessário) ===" -ForegroundColor Cyan
    Push-Location $distDir
    pip install -r requirements.txt -q
    Pop-Location

    $mappingName = if ($env:SHM_MAPPING_NAME) { $env:SHM_MAPPING_NAME } else { "Local\PQMarketDataV1" }
    $shmSizeMb = if ($env:SHM_SIZE_MB) { $env:SHM_SIZE_MB } else { "64" }
    $env:IPC_MODE = "shm"
    $env:SHM_ENABLED = "1"
    $env:SHM_MAPPING_NAME = $mappingName
    $env:SHM_SIZE_MB = $shmSizeMb

    $launcherLogDir = Join-Path $root "tmp"
    New-Item -ItemType Directory -Path $launcherLogDir -Force | Out-Null
    $engineStdOut = Join-Path $launcherLogDir "run-dev2-engine.out.log"
    $engineStdErr = Join-Path $launcherLogDir "run-dev2-engine.err.log"
    $distStdOut = Join-Path $launcherLogDir "run-dev2-distributor.out.log"
    $distStdErr = Join-Path $launcherLogDir "run-dev2-distributor.err.log"
    foreach ($path in @($engineStdOut, $engineStdErr, $distStdOut, $distStdErr)) {
        if (Test-Path $path) {
            Remove-Item $path -Force
        }
    }

    Write-Host "=== Iniciando engine com SHM_ENABLED=1 ===" -ForegroundColor Cyan
    Write-Host "IPC_MODE=shm SHM_MAPPING_NAME=$mappingName SHM_SIZE_MB=$shmSizeMb RequireShmMapping=$RequireShmMapping ShmProbeTimeoutSeconds=$ShmProbeTimeoutSeconds" -ForegroundColor Gray
    $engineProcess = Start-Process -FilePath $engineExe -WorkingDirectory $engineDir -RedirectStandardOutput $engineStdOut -RedirectStandardError $engineStdErr -PassThru

    $probeTimeout = [Math]::Max(1, $ShmProbeTimeoutSeconds)
    $mappingReady = Wait-ForSharedMemoryMapping -MappingName $mappingName -SizeMb ([int]$shmSizeMb) -TimeoutSeconds $probeTimeout
    if (-not $mappingReady) {
        $msg = "Shared memory mapping not available after engine startup."
        if ($RequireShmMapping) {
            throw $msg
        }
        Write-Host "$msg Continuando startup; distributor pode cair em fallback SHM→ZMQ." -ForegroundColor Yellow
    }

    Write-Host "=== Iniciando distributor em SHM ===" -ForegroundColor Cyan
    $distProcess = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory $distDir -RedirectStandardOutput $distStdOut -RedirectStandardError $distStdErr -PassThru

    Write-Host "Teste SHM ativo." -ForegroundColor Green
    Write-Host "- Distributor PID: $($distProcess.Id)" -ForegroundColor Gray
    Write-Host "- Engine PID: $($engineProcess.Id)" -ForegroundColor Gray
    Write-Host "- Engine logs: $engineStdOut / $engineStdErr" -ForegroundColor Gray
    Write-Host "- Distributor logs: $distStdOut / $distStdErr" -ForegroundColor Gray
    Write-Host "Pressione Ctrl+C para encerrar ambos." -ForegroundColor Yellow

    while ($true) {
        Start-Sleep -Seconds 1
        if ($engineProcess.HasExited) { throw "engine.exe encerrou com código $($engineProcess.ExitCode)." }
        if ($distProcess.HasExited) { throw "distributor encerrou com código $($distProcess.ExitCode)." }
    }
}
finally {
    if ($engineProcess -and -not $engineProcess.HasExited) {
        Stop-Process -Id $engineProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($distProcess -and -not $distProcess.HasExited) {
        Stop-Process -Id $distProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Kill-StaleProcesses
}
