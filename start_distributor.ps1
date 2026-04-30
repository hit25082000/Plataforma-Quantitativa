# start_distributor.ps1
# Inicia o distributor Python com todas as variáveis do .env carregadas corretamente.

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$ENV_FILE = Join-Path $ROOT ".env"
$DIST_DIR = Join-Path $ROOT "distributor"

Write-Host "==> Carregando .env..." -ForegroundColor Cyan

# Lê apenas linhas KEY=VALUE (ignora comentários e sintaxe $env:)
Get-Content $ENV_FILE | Where-Object { $_ -match '^[A-Z_]+=.+' -and $_ -notmatch '^\$env:' } | ForEach-Object {
    $parts = $_ -split '=', 2
    $key   = $parts[0].Trim()
    $value = ($parts[1] -replace '\s*#.*$', '').Trim()
    Set-Item "env:$key" $value
    Write-Host "  $key = $($value.Substring(0, [Math]::Min(8, $value.Length)))..." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "==> GOOGLE_API_KEY configurada: $( if ($env:GOOGLE_API_KEY) { 'SIM ✓' } else { 'NÃO ✗' } )" -ForegroundColor $(if ($env:GOOGLE_API_KEY) { 'Green' } else { 'Red' })
Write-Host ""
Write-Host "==> Iniciando distributor em $DIST_DIR..." -ForegroundColor Cyan

Set-Location $DIST_DIR
python main.py
