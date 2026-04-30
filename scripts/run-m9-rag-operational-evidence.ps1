param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Ticker = "WINFUT",
    [double]$DurationSeconds = 120,
    [double]$IntervalSeconds = 5,
    [double]$TimeoutSeconds = 4,
    [double]$WarmupSeconds = 45,
    [int]$WarmupMinOkSamples = 2,
    [switch]$WarmupRequireRouteGrowth,
    [int]$WatchdogConsecutiveHttpFailures = 8,
    [int]$MaxAttempts = 2,
    [double]$RerunBackoffSeconds = 8,
    [switch]$DisableRerunOnHealthDrop,
    [string]$OutDir = "",
    [string]$SqlitePath = "",
    [string]$ExpectViewsBackend = "",
    [int]$MaxHttpFailures = 3,
    [int]$MaxLagMs = 30000,
    [int]$MinViewsIngestedDelta = 1,
    [switch]$RequireRouteTotalDelta
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "scripts\run_m9_rag_operational_evidence.py"

$argsList = @(
    "--base-url", $BaseUrl,
    "--ticker", $Ticker,
    "--duration-seconds", ([string]$DurationSeconds),
    "--interval-seconds", ([string]$IntervalSeconds),
    "--timeout-seconds", ([string]$TimeoutSeconds),
    "--warmup-seconds", ([string]$WarmupSeconds),
    "--warmup-min-ok-samples", ([string]$WarmupMinOkSamples),
    "--watchdog-consecutive-http-failures", ([string]$WatchdogConsecutiveHttpFailures),
    "--max-attempts", ([string]$MaxAttempts),
    "--rerun-backoff-seconds", ([string]$RerunBackoffSeconds),
    "--max-http-failures", ([string]$MaxHttpFailures),
    "--max-lag-ms", ([string]$MaxLagMs),
    "--min-views-ingested-delta", ([string]$MinViewsIngestedDelta)
)

if ($OutDir) { $argsList += @("--out-dir", $OutDir) }
if ($SqlitePath) {
    $resolvedSqlitePath = if ([System.IO.Path]::IsPathRooted($SqlitePath)) {
        $SqlitePath
    } else {
        Join-Path $root $SqlitePath
    }
    $argsList += @("--sqlite-path", $resolvedSqlitePath)
}
if ($ExpectViewsBackend) { $argsList += @("--expect-views-backend", $ExpectViewsBackend) }
if ($RequireRouteTotalDelta) { $argsList += "--require-route-total-delta" }
if ($WarmupRequireRouteGrowth) { $argsList += "--warmup-require-route-growth" }
if ($DisableRerunOnHealthDrop) { $argsList += "--disable-rerun-on-health-drop" }

Set-Location $root
python $py @argsList
