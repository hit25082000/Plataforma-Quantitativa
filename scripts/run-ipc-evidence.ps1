param(
    [ValidateSet("latency", "stress", "session", "all")]
    [string]$Mode = "latency",
    [string]$OutDir,
    [int]$Messages = 50000,
    [int]$Warmup = 500,
    [int]$StressRate = 100000,
    [double]$StressSeconds = 3.0,
    [int]$StressMaxDropped = 0,
    [int]$StressMaxCrcMismatch = 0,
    [int]$StressMaxPayloadMismatch = 0,
    [double]$StressMinAchievedRate = 0,
    [double]$StressMinAchievedRateRatio = 0,
    [switch]$StressFailOnDrop,
    [double]$SessionSeconds = 21600,
    [int]$SessionMaxGapMessages = 0,
    [int]$SessionMaxRingDropped = 0,
    [int]$SessionMaxCommittedMismatch = 0,
    [int]$SessionMaxCrcMismatch = 0,
    [int]$SessionMaxPayloadMismatch = 0,
    [int]$SessionMinObservedTrades = 0,
    [switch]$SessionFailOnLoss,
    [int]$ShmMb = 64,
    [string]$ZmqUrl = "tcp://127.0.0.1:37591",
    [string]$ShmName = "Local\PQBenchIpcV1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$benchScript = Join-Path $root "scripts\benchmark_ipc_zmq_vs_shm.py"

if (-not (Test-Path $benchScript)) {
    throw "Benchmark script not found: $benchScript"
}

if (-not $OutDir -or [string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $root "distributor\logs\ipc-evidence-$stamp"
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$shmNameBound = $PSBoundParameters.ContainsKey("ShmName")
if (-not $shmNameBound -and $Mode -in @("session", "all")) {
    $ShmName = "Local\PQMarketDataV1"
}

function Invoke-Benchmark {
    param(
        [string]$Label,
        [string[]]$ExtraArgs,
        [string]$OutFile
    )

    Write-Host "=== $Label ===" -ForegroundColor Cyan
    Write-Host "Out: $OutFile" -ForegroundColor Gray
    $manifestFile = [System.IO.Path]::ChangeExtension($OutFile, ".manifest.json")
    $args = @($benchScript, "--out", $OutFile, "--zmq-url", $ZmqUrl, "--shm-name", $ShmName, "--shm-mb", "$ShmMb")
    $args += $ExtraArgs
    & python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark failed for $Label with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path $OutFile)) {
        throw "Benchmark did not create output CSV: $OutFile"
    }
    if (-not (Test-Path $manifestFile)) {
        throw "Benchmark did not create manifest: $manifestFile"
    }
    Write-Host "Verified: $OutFile" -ForegroundColor Green
    Write-Host "Verified: $manifestFile" -ForegroundColor Green
}

$runLatency = $Mode -in @("latency", "all")
$runStress = $Mode -in @("stress", "all")
$runSession = $Mode -in @("session", "all")

if ($runLatency) {
    $latencyCsv = Join-Path $OutDir "latency.csv"
    Invoke-Benchmark -Label "Latency benchmark" -ExtraArgs @("--messages", "$Messages", "--warmup", "$Warmup") -OutFile $latencyCsv
}

if ($runStress) {
    if ($env:OS -ne "Windows_NT") {
        Write-Host "Skipping stress mode: SHM stress requires Windows." -ForegroundColor Yellow
    } else {
        $stressCsv = Join-Path $OutDir "stress.csv"
        $stressArgs = @(
            "--stress",
            "--stress-rate", "$StressRate",
            "--stress-seconds", "$StressSeconds",
            "--stress-max-dropped", "$StressMaxDropped",
            "--stress-max-crc-mismatch", "$StressMaxCrcMismatch",
            "--stress-max-payload-mismatch", "$StressMaxPayloadMismatch",
            "--stress-min-achieved-rate", "$StressMinAchievedRate",
            "--stress-min-achieved-rate-ratio", "$StressMinAchievedRateRatio"
        )
        if ($StressFailOnDrop) {
            $stressArgs += "--stress-fail-on-drop"
        }
        Invoke-Benchmark -Label "Stress benchmark" -ExtraArgs $stressArgs -OutFile $stressCsv
    }
}

if ($runSession) {
    if ($env:OS -ne "Windows_NT") {
        Write-Host "Skipping session mode: SHM session diagnostics requires Windows." -ForegroundColor Yellow
    } else {
        $sessionCsv = Join-Path $OutDir "session.csv"
        $sessionArgs = @(
            "--session",
            "--session-seconds", "$SessionSeconds",
            "--session-max-gap-messages", "$SessionMaxGapMessages",
            "--session-max-ring-dropped", "$SessionMaxRingDropped",
            "--session-max-committed-mismatch", "$SessionMaxCommittedMismatch",
            "--session-max-crc-mismatch", "$SessionMaxCrcMismatch",
            "--session-max-payload-mismatch", "$SessionMaxPayloadMismatch",
            "--session-min-observed-trades", "$SessionMinObservedTrades"
        )
        if ($SessionFailOnLoss) {
            $sessionArgs += "--session-fail-on-loss"
        }
        Invoke-Benchmark -Label "Session diagnostics" -ExtraArgs $sessionArgs -OutFile $sessionCsv
    }
}

Write-Host "Evidence written to $OutDir" -ForegroundColor Green
