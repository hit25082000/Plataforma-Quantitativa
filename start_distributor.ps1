# start_distributor.ps1
# Inicia o distributor Python com todas as variáveis do .env carregadas corretamente.

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$ENV_FILE = Join-Path $ROOT ".env"
$ENV_LOCAL_FILE = Join-Path $ROOT ".env.local"
$DIST_DIR = Join-Path $ROOT "distributor"

Write-Host "==> Carregando .env..." -ForegroundColor Cyan

function Load-DotEnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | Where-Object { $_ -match '^[A-Z_]+=.+' -and $_ -notmatch '^\$env:' } | ForEach-Object {
        $parts = $_ -split '=', 2
        $key   = $parts[0].Trim()
        $value = ($parts[1] -replace '\s*#.*$', '').Trim()
        Set-Item "env:$key" $value
        Write-Host "  $key = $($value.Substring(0, [Math]::Min(8, $value.Length)))..." -ForegroundColor DarkGray
    }
}

Load-DotEnvFile -Path $ENV_FILE
Load-DotEnvFile -Path $ENV_LOCAL_FILE

if ([string]::IsNullOrWhiteSpace($env:IPC_MODE)) {
    $env:IPC_MODE = "zmq"
}
if ([string]::IsNullOrWhiteSpace($env:SHM_FALLBACK_PROBE_TIMEOUT_MS)) {
    $env:SHM_FALLBACK_PROBE_TIMEOUT_MS = "3000"
}

Write-Host ""
Write-Host "==> GOOGLE_API_KEY configurada: $( if ($env:GOOGLE_API_KEY) { 'SIM ✓' } else { 'NÃO ✗' } )" -ForegroundColor $(if ($env:GOOGLE_API_KEY) { 'Green' } else { 'Red' })
Write-Host "==> IPC_MODE=$($env:IPC_MODE) SHM_FALLBACK_PROBE_TIMEOUT_MS=$($env:SHM_FALLBACK_PROBE_TIMEOUT_MS)" -ForegroundColor Gray
Write-Host ""
Write-Host "==> Iniciando distributor em $DIST_DIR..." -ForegroundColor Cyan

Set-Location $DIST_DIR
python main.py
