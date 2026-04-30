param(
    [string]$RepoRoot = "",
    [switch]$FailOnWarning
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$baseDir = Join-Path $RepoRoot "logs\pre-release"
$outDir = Join-Path $baseDir "installer-readiness-$timestamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$sanityCmd = @(
    "scripts\run_ocr_overlay_prerelease_sanity.py",
    "--out-dir", "logs\pre-release"
)
if ($FailOnWarning) {
    $sanityCmd += "--fail-on-warning"
}

$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param(
        [string]$CheckId,
        [string]$Status,
        [string]$Detail
    )
    $checks.Add([pscustomobject]@{
            check_id = $CheckId
            status   = $Status
            detail   = $Detail
        })
}

Push-Location $RepoRoot
try {
    & python @sanityCmd
    $sanityExit = $LASTEXITCODE
    if ($sanityExit -eq 0) {
        Add-Check -CheckId "preflight:overlay-sanity" -Status "ok" -Detail "run_ocr_overlay_prerelease_sanity.py sem falhas bloqueantes"
    } elseif ($sanityExit -eq 2) {
        Add-Check -CheckId "preflight:overlay-sanity" -Status "fail" -Detail "run_ocr_overlay_prerelease_sanity.py reportou bloqueios (exit=2)"
    } else {
        Add-Check -CheckId "preflight:overlay-sanity" -Status "fail" -Detail "run_ocr_overlay_prerelease_sanity.py falhou (exit=$sanityExit)"
    }
} catch {
    Add-Check -CheckId "preflight:overlay-sanity" -Status "fail" -Detail "erro ao executar sanity: $($_.Exception.Message)"
} finally {
    Pop-Location
}

$criticalScripts = @(
    "scripts/build-installer.ps1",
    "scripts/sync-profit-ocr-to-tauri-resources.ps1",
    "scripts/run_ocr_overlay_prerelease_sanity.py"
)

foreach ($rel in $criticalScripts) {
    $full = Join-Path $RepoRoot $rel
    if (Test-Path $full) {
        Add-Check -CheckId "presence:$rel" -Status "ok" -Detail "script presente"
    } else {
        Add-Check -CheckId "presence:$rel" -Status "fail" -Detail "script ausente"
    }
}

$buildInstallerPath = Join-Path $RepoRoot "scripts\build-installer.ps1"
if (Test-Path $buildInstallerPath) {
    $buildInstallerRaw = Get-Content -Raw -Path $buildInstallerPath
    $scriptAssertions = @(
        @{ id = "build-installer:sync-profit-ocr"; needle = "sync-profit-ocr-to-tauri-resources.ps1"; detail = "sincronizacao OCR para Tauri resources" },
        @{ id = "build-installer:copy-engine"; needle = "engine.exe"; detail = "copia de engine.exe para resources" },
        @{ id = "build-installer:copy-distributor"; needle = "distributor.exe"; detail = "copia de distributor.exe para resources" },
        @{ id = "build-installer:copy-ocr-service-exe"; needle = "profit_ocr_service.exe"; detail = "copia de profit_ocr_service.exe para resources" },
        @{ id = "build-installer:copy-profitdll64"; needle = "ProfitDLL64.dll"; detail = "copia/validacao de ProfitDLL64.dll" }
    )
    foreach ($assertion in $scriptAssertions) {
        if ($buildInstallerRaw -match [regex]::Escape($assertion.needle)) {
            Add-Check -CheckId $assertion.id -Status "ok" -Detail $assertion.detail
        } else {
            Add-Check -CheckId $assertion.id -Status "fail" -Detail "$($assertion.detail) nao encontrada no build-installer.ps1"
        }
    }
}

$tauriConfPath = Join-Path $RepoRoot "app\src-tauri\tauri.conf.json"
if (-not (Test-Path $tauriConfPath)) {
    Add-Check -CheckId "tauri:config" -Status "fail" -Detail "app/src-tauri/tauri.conf.json ausente"
} else {
    try {
        $tauriConf = Get-Content -Raw -Path $tauriConfPath | ConvertFrom-Json
        $resources = @()
        if ($tauriConf.bundle -and $tauriConf.bundle.resources) {
            $resources = @($tauriConf.bundle.resources | ForEach-Object { [string]$_ })
        }
        $requiredBundle = @(
            "resources/profit_ocr_service.py",
            "resources/ocr_overlay_audit.py",
            "resources/profit_ocr_service.exe",
            "resources/engine.exe",
            "resources/distributor.exe",
            "resources/ProfitDLL64.dll"
        )
        foreach ($entry in $requiredBundle) {
            if ($resources -contains $entry) {
                Add-Check -CheckId "bundle:$entry" -Status "ok" -Detail "entrada declarada em bundle.resources"
            } else {
                Add-Check -CheckId "bundle:$entry" -Status "fail" -Detail "entrada ausente em bundle.resources"
            }
        }
    } catch {
        Add-Check -CheckId "tauri:config" -Status "fail" -Detail "tauri.conf.json invalido: $($_.Exception.Message)"
    }
}

$counts = @{ ok = 0; warn = 0; fail = 0 }
foreach ($item in $checks) {
    if ($counts.ContainsKey($item.status)) {
        $counts[$item.status] += 1
    } else {
        $counts[$item.status] = 1
    }
}

$overallOk = ($counts.fail -eq 0) -and (-not ($FailOnWarning -and $counts.warn -gt 0))
$blockers = @($checks | Where-Object { $_.status -eq "fail" } | ForEach-Object { $_.check_id })
$warnings = @($checks | Where-Object { $_.status -eq "warn" } | ForEach-Object { $_.check_id })

$reportMd = Join-Path $outDir "report.md"
$manifest = Join-Path $outDir "report.manifest.json"
$generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$lines = @(
    "# Installer Readiness Report (Overlay Stable)",
    "",
    "- generated_at: $generatedAt",
    "- overall_ok: $([int]$overallOk)",
    "- ok: $($counts.ok)",
    "- warn: $($counts.warn)",
    "- fail: $($counts.fail)",
    "",
    "## Blockers",
    ""
)
if ($blockers.Count -eq 0) {
    $lines += "- none"
} else {
    foreach ($blocker in $blockers) {
        $lines += "- $blocker"
    }
}
$lines += @(
    "",
    "## Checks",
    "",
    "| check_id | status | detail |",
    "| --- | --- | --- |"
)
foreach ($item in $checks) {
    $lines += "| $($item.check_id) | $($item.status) | $($item.detail) |"
}
$lines -join "`n" | Set-Content -Path $reportMd -Encoding UTF8

$manifestObj = [ordered]@{
    runner               = "verify-installer-readiness.ps1"
    overall_ok           = [bool]$overallOk
    fail_on_warning      = [bool]$FailOnWarning
    counts               = $counts
    blockers             = $blockers
    warnings             = $warnings
    generated_at_iso     = (Get-Date).ToString("o")
    artifacts            = @{
        report_md = $reportMd
        manifest  = $manifest
    }
    checks               = @($checks)
}
$manifestObj | ConvertTo-Json -Depth 8 | Set-Content -Path $manifest -Encoding UTF8

Write-Host "Wrote: $reportMd"
Write-Host "Wrote: $manifest"
if (-not $overallOk) {
    exit 2
}
exit 0
