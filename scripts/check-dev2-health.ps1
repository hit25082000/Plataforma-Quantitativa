param(
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$uri = "http://127.0.0.1:8000/health"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastErr = $null

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 3
        if ($resp.status -eq "ok") {
            Write-Host "Health OK" -ForegroundColor Green
            Write-Host ("ipc_mode={0} backlog={1} route_total={2} dropped_dom_total={3} gap_count_total={4}" -f `
                $resp.ipc_mode, $resp.backlog, $resp.route_total, $resp.dropped_dom_total, $resp.gap_count_total)
            if ($null -ne $resp.gap_messages_total -or $null -ne $resp.ring_dropped_total) {
                Write-Host ("gap_messages_total={0} ring_dropped_total={1}" -f `
                    $resp.gap_messages_total, $resp.ring_dropped_total)
            }
            exit 0
        }
        $lastErr = "Resposta inesperada: status=$($resp.status)"
    } catch {
        $lastErr = $_.Exception.Message
    }
    Start-Sleep -Milliseconds 700
}

Write-Host "Health check falhou em $TimeoutSeconds s: $lastErr" -ForegroundColor Red
if (Test-Path ".\tmp\run-dev2-distributor.err.log") {
    Write-Host "--- tail tmp/run-dev2-distributor.err.log ---" -ForegroundColor Yellow
    Get-Content ".\tmp\run-dev2-distributor.err.log" -Tail 40
}
if (Test-Path ".\tmp\run-dev2-distributor.out.log") {
    Write-Host "--- tail tmp/run-dev2-distributor.out.log ---" -ForegroundColor Yellow
    Get-Content ".\tmp\run-dev2-distributor.out.log" -Tail 40
}
if (Test-Path ".\tmp\run-dev2-engine.err.log") {
    Write-Host "--- tail tmp/run-dev2-engine.err.log ---" -ForegroundColor Yellow
    Get-Content ".\tmp\run-dev2-engine.err.log" -Tail 40
}
Write-Host "Dica: execute scripts/run-dev2.ps1 (sem -RequireShmMapping para startup mais rápido) e tente novamente." -ForegroundColor Yellow
exit 1
