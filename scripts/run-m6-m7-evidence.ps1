param(
    [string]$PythonExe = "python",
    [string]$OutDir,
    [string]$HftScript,
    [string]$IpcScript,
    [string]$EngineExe,
    [string]$WorkDir,
    [double]$HftDurationSeconds = 3600,
    [int]$HftWindows = 1,
    [double]$HftTotalSeconds = 0,
    [string]$HftRuns = "baseline,pinned",
    [switch]$HftEnableShmQpc,
    [int]$HftQpcSampleEvery = 1,
    [int]$HftQpcMaxSamples = 1000000,
    [int]$ShmQpcSampleEvery = 1,
    [int]$ShmQpcMaxSamples = 1000000,
    [int]$HftMainCore = 0,
    [int]$HftPublisherCore = 1,
    [int]$HftProfitCallbackCore = 2,
    [ValidateSet("physical", "logical")]
    [string]$HftCoreIndexMode = "physical",
    [int]$HftPrefetch = 1,
    [string]$HftCheckRun = "pinned",
    [string]$HftCheckMetric = "shm_write_trade_duration",
    [int]$HftTargetP99Ns = 10000,
    [int]$HftTargetP999Ns = 20000,
    [int]$HftAggregateMaxFailedWindows = -1,
    [int]$HftAggregateMaxP99Ns = -1,
    [int]$HftAggregateMaxP999Ns = -1,
    [switch]$HftFailOnCheck,
    [switch]$HftShmLargePagesStrict,
    [int]$HftShmPrefetchNextSlot = 1,
    [string]$MatrixShmLargePages = "0,1",
    [string]$MatrixShmNumaNodes = "-1,0",
    [double]$SessionSeconds = 21600,
    [int]$SessionWindows = 1,
    [double]$SessionTotalSeconds = 0,
    [string]$SessionShmName = "Local\PQMarketDataV1",
    [int]$SessionShmMb = 64,
    [int]$SessionMaxGapMessages = 0,
    [int]$SessionMaxRingDropped = 0,
    [int]$SessionMaxCommittedMismatch = 0,
    [int]$SessionMaxCrcMismatch = 0,
    [int]$SessionMaxPayloadMismatch = 0,
    [int]$SessionMinObservedTrades = 0,
    [int]$SessionAggregateMaxGapMessages = -1,
    [int]$SessionAggregateMaxRingDropped = -1,
    [int]$SessionAggregateMaxCommittedMismatch = -1,
    [int]$SessionAggregateMaxCrcMismatch = -1,
    [int]$SessionAggregateMaxPayloadMismatch = -1,
    [int]$SessionAggregateMinObservedTrades = -1,
    [switch]$SessionFailOnLoss,
    [int]$HftMaxRetries = 0,
    [int]$IpcMaxRetries = 0,
    [double]$RetryDelaySeconds = 3.0,
    [switch]$StopOnError,
    [switch]$Resume,
    [switch]$ResumeAllowFailed,
    [switch]$FailOnAny = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runnerScript = Join-Path $root "scripts\run_m6_m7_evidence.py"

if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found: $runnerScript"
}

if (-not $OutDir -or [string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $root "distributor\logs\m6-m7-evidence-$stamp"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$args = @(
    $runnerScript,
    "--python-exe", $PythonExe,
    "--out-dir", $OutDir,
    "--hft-duration-seconds", "$HftDurationSeconds",
    "--hft-windows", "$HftWindows",
    "--hft-runs", $HftRuns,
    "--hft-qpc-sample-every", "$HftQpcSampleEvery",
    "--hft-qpc-max-samples", "$HftQpcMaxSamples",
    "--shm-qpc-sample-every", "$ShmQpcSampleEvery",
    "--shm-qpc-max-samples", "$ShmQpcMaxSamples",
    "--hft-main-core", "$HftMainCore",
    "--hft-publisher-core", "$HftPublisherCore",
    "--hft-profit-callback-core", "$HftProfitCallbackCore",
    "--hft-core-index-mode", $HftCoreIndexMode,
    "--hft-prefetch", "$HftPrefetch",
    "--hft-check-run", $HftCheckRun,
    "--hft-check-metric", $HftCheckMetric,
    "--hft-target-p99-ns", "$HftTargetP99Ns",
    "--hft-target-p999-ns", "$HftTargetP999Ns",
    "--hft-aggregate-max-failed-windows", "$HftAggregateMaxFailedWindows",
    "--hft-aggregate-max-p99-ns", "$HftAggregateMaxP99Ns",
    "--hft-aggregate-max-p999-ns", "$HftAggregateMaxP999Ns",
    "--hft-shm-prefetch-next-slot", "$HftShmPrefetchNextSlot",
    "--matrix-shm-large-pages=$MatrixShmLargePages",
    "--matrix-shm-numa-nodes=$MatrixShmNumaNodes",
    "--session-seconds", "$SessionSeconds",
    "--session-windows", "$SessionWindows",
    "--session-shm-name", $SessionShmName,
    "--session-shm-mb", "$SessionShmMb",
    "--session-max-gap-messages", "$SessionMaxGapMessages",
    "--session-max-ring-dropped", "$SessionMaxRingDropped",
    "--session-max-committed-mismatch", "$SessionMaxCommittedMismatch",
    "--session-max-crc-mismatch", "$SessionMaxCrcMismatch",
    "--session-max-payload-mismatch", "$SessionMaxPayloadMismatch",
    "--session-min-observed-trades", "$SessionMinObservedTrades",
    "--session-aggregate-max-gap-messages", "$SessionAggregateMaxGapMessages",
    "--session-aggregate-max-ring-dropped", "$SessionAggregateMaxRingDropped",
    "--session-aggregate-max-committed-mismatch", "$SessionAggregateMaxCommittedMismatch",
    "--session-aggregate-max-crc-mismatch", "$SessionAggregateMaxCrcMismatch",
    "--session-aggregate-max-payload-mismatch", "$SessionAggregateMaxPayloadMismatch",
    "--session-aggregate-min-observed-trades", "$SessionAggregateMinObservedTrades",
    "--hft-max-retries", "$HftMaxRetries",
    "--ipc-max-retries", "$IpcMaxRetries",
    "--retry-delay-seconds", "$RetryDelaySeconds"
)

if ($HftEnableShmQpc) {
    $args += "--hft-enable-shm-qpc"
}
if ($HftTotalSeconds -gt 0) {
    $args += @("--hft-total-seconds", "$HftTotalSeconds")
}
if ($HftScript -and -not [string]::IsNullOrWhiteSpace($HftScript)) {
    $args += @("--hft-script", $HftScript)
}
if ($IpcScript -and -not [string]::IsNullOrWhiteSpace($IpcScript)) {
    $args += @("--ipc-script", $IpcScript)
}
if ($EngineExe -and -not [string]::IsNullOrWhiteSpace($EngineExe)) {
    $args += @("--engine", $EngineExe)
}
if ($WorkDir -and -not [string]::IsNullOrWhiteSpace($WorkDir)) {
    $args += @("--workdir", $WorkDir)
}
if ($HftFailOnCheck) {
    $args += "--hft-fail-on-check"
}
if ($HftShmLargePagesStrict) {
    $args += "--hft-shm-large-pages-strict"
}
if ($SessionFailOnLoss) {
    $args += "--session-fail-on-loss"
}
if ($SessionTotalSeconds -gt 0) {
    $args += @("--session-total-seconds", "$SessionTotalSeconds")
}
if ($StopOnError) {
    $args += "--stop-on-error"
}
if ($Resume) {
    $args += "--resume"
}
if ($ResumeAllowFailed) {
    $args += "--resume-allow-failed"
}
if (-not $FailOnAny) {
    $args += "--no-fail-on-any"
}

Write-Host "=== M6/M7 evidence ===" -ForegroundColor Cyan
Write-Host "out=$OutDir hft_duration=$HftDurationSeconds hft_total=$HftTotalSeconds session_seconds=$SessionSeconds session_total=$SessionTotalSeconds session_windows=$SessionWindows matrix_lp=$MatrixShmLargePages matrix_numa=$MatrixShmNumaNodes" -ForegroundColor Gray
& $PythonExe @args
$exitCode = $LASTEXITCODE

$summaryCsv = Join-Path $OutDir "summary.csv"
$summaryMarkdown = Join-Path $OutDir "summary.md"
$summaryManifest = Join-Path $OutDir "summary.manifest.json"
if ($exitCode -ne 0 -and -not (Test-Path $summaryCsv) -and -not (Test-Path $summaryManifest) -and -not (Test-Path $summaryMarkdown)) {
    exit $exitCode
}
if (-not (Test-Path $summaryCsv)) {
    throw "Missing summary CSV: $summaryCsv"
}
if (-not (Test-Path $summaryMarkdown)) {
    throw "Missing summary markdown: $summaryMarkdown"
}
if (-not (Test-Path $summaryManifest)) {
    throw "Missing summary manifest: $summaryManifest"
}

Write-Host "Verified: $summaryCsv" -ForegroundColor Green
Write-Host "Verified: $summaryMarkdown" -ForegroundColor Green
Write-Host "Verified: $summaryManifest" -ForegroundColor Green
if ($exitCode -ne 0) {
    exit $exitCode
}
