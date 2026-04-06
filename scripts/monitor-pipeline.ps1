# Monitoriza o distributor: GET /health em loop e, opcionalmente, segue um ficheiro de log.
# Requer Python 3 no PATH.
#
# Exemplos:
#   .\scripts\monitor-pipeline.ps1
#   .\scripts\monitor-pipeline.ps1 -Interval 2
#   .\scripts\monitor-pipeline.ps1 -Log distributor-run.log

param(
    [string]$Url = $env:MONITOR_HEALTH_URL,
    [double]$Interval = 5,
    [string]$Log = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Url) { $Url = "http://127.0.0.1:8000/health" }

$py = Join-Path $root "scripts\monitor_pipeline.py"
$argsList = @("--url", $Url, "--interval", ([string]$Interval))
if ($Log) {
    $logPath = if ([System.IO.Path]::IsPathRooted($Log)) { $Log } else { Join-Path $root $Log }
    $argsList += @("--log", $logPath)
}

Set-Location $root
python $py @argsList
