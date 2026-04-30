param(
    [ValidateSet("baseline", "pinned", "all")]
    [string]$Mode = "all",
    [double]$DurationSeconds = 120,
    [string]$OutDir,
    [string]$EngineExe,
    [string]$WorkDir,
    [switch]$EnableShmQpc,
    [switch]$ShmLargePages,
    [switch]$ShmLargePagesStrict,
    [int]$ShmNumaNode = -1,
    [int]$ShmPrefetchNextSlot = 1,
    [ValidateSet("physical", "logical")]
    [string]$CoreIndexMode = "physical",
    [int]$HftPrefetch = 1,
    [string]$CheckRun = "pinned",
    [string]$CheckMetric = "shm_write_trade_duration",
    [int]$TargetP99Ns = 10000,
    [int]$TargetP999Ns = 20000,
    [switch]$FailOnCheck,
    [switch]$RunMatrix,
    [string]$MatrixShmLargePages = "0,1",
    [string]$MatrixShmNumaNodes = "-1,0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$benchScript = Join-Path $root "scripts\benchmark_hft_qpc.py"

if (-not (Test-Path $benchScript)) {
    throw "Benchmark script not found: $benchScript"
}

if (-not $OutDir -or [string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $root "distributor\logs\hft-qpc-evidence-$stamp"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

if (-not $EngineExe -or [string]::IsNullOrWhiteSpace($EngineExe)) {
    $EngineExe = Join-Path $root "engine\build\Release\engine.exe"
}
if (-not $WorkDir -or [string]::IsNullOrWhiteSpace($WorkDir)) {
    $WorkDir = Join-Path $root "engine\build\Release"
}

function Resolve-Runs {
    param([string]$RunMode)
    if ($RunMode -eq "all") {
        return "baseline,pinned"
    }
    if ($RunMode -eq "baseline") {
        return "baseline"
    }
    return "pinned"
}

function Parse-IntList {
    param(
        [string]$Raw,
        [string]$Name
    )
    if ([string]::IsNullOrWhiteSpace($Raw)) {
        throw "$Name cannot be empty."
    }
    $items = @()
    foreach ($part in ($Raw -split ",")) {
        $token = $part.Trim()
        if ([string]::IsNullOrWhiteSpace($token)) {
            continue
        }
        $value = 0
        if (-not [int]::TryParse($token, [ref]$value)) {
            throw "Invalid integer '$token' in $Name."
        }
        $items += $value
    }
    if ($items.Count -eq 0) {
        throw "$Name must contain at least one integer value."
    }
    return $items
}

function Parse-BinaryList {
    param(
        [string]$Raw,
        [string]$Name
    )
    $values = Parse-IntList -Raw $Raw -Name $Name
    foreach ($value in $values) {
        if ($value -ne 0 -and $value -ne 1) {
            throw "$Name accepts only 0 or 1 values."
        }
    }
    return $values
}

function Invoke-BenchmarkScenario {
    param(
        [string]$RunMode,
        [bool]$UseLargePages,
        [int]$NumaNode,
        [string]$Label,
        [string]$OutCsv
    )

    $runs = Resolve-Runs -RunMode $RunMode
    $args = @(
        $benchScript,
        "--engine", $EngineExe,
        "--workdir", $WorkDir,
        "--duration-seconds", "$DurationSeconds",
        "--runs", $runs,
        "--hft-core-index-mode", $CoreIndexMode,
        "--hft-prefetch", "$HftPrefetch",
        "--shm-numa-node", "$NumaNode",
        "--shm-prefetch-next-slot", "$ShmPrefetchNextSlot",
        "--check-run", $CheckRun,
        "--check-metric", $CheckMetric,
        "--target-p99-ns", "$TargetP99Ns",
        "--target-p999-ns", "$TargetP999Ns",
        "--out", $OutCsv
    )
    if ($EnableShmQpc) {
        $args += "--enable-shm-qpc"
    }
    if ($UseLargePages) {
        $args += "--shm-large-pages"
    }
    if ($ShmLargePagesStrict) {
        $args += "--shm-large-pages-strict"
    }
    if ($FailOnCheck) {
        $args += "--fail-on-check"
    }

    Write-Host "=== $Label ===" -ForegroundColor Cyan
    Write-Host "mode=$RunMode runs=$runs duration=$DurationSeconds lp=$([int]$UseLargePages) numa=$NumaNode out=$OutCsv" -ForegroundColor Gray
    & python @args
    if ($LASTEXITCODE -ne 0) {
        throw "benchmark_hft_qpc.py failed with exit code $LASTEXITCODE"
    }

    $manifest = [System.IO.Path]::ChangeExtension($OutCsv, ".manifest.json")
    if (-not (Test-Path $OutCsv)) {
        throw "Missing output CSV: $OutCsv"
    }
    if (-not (Test-Path $manifest)) {
        throw "Missing output manifest: $manifest"
    }
    Write-Host "Verified: $OutCsv" -ForegroundColor Green
    Write-Host "Verified: $manifest" -ForegroundColor Green

    return [PSCustomObject]@{
        label = $Label
        runs = $runs
        out_csv = $OutCsv
        out_manifest = $manifest
        shm_large_pages = [int]$UseLargePages
        shm_numa_node = $NumaNode
    }
}

if (-not $RunMatrix) {
    $single = Invoke-BenchmarkScenario `
        -RunMode $Mode `
        -UseLargePages ([bool]$ShmLargePages) `
        -NumaNode $ShmNumaNode `
        -Label "HFT QPC evidence" `
        -OutCsv (Join-Path $OutDir "summary.csv")
    return
}

$matrixLargePages = Parse-BinaryList -Raw $MatrixShmLargePages -Name "MatrixShmLargePages"
$matrixNumaNodes = Parse-IntList -Raw $MatrixShmNumaNodes -Name "MatrixShmNumaNodes"
$matrixResults = @()

foreach ($lp in $matrixLargePages) {
    foreach ($numa in $matrixNumaNodes) {
        $numaLabel = if ($numa -ge 0) { "numa$numa" } else { "numa_auto" }
        $scenario = "lp$lp-$numaLabel"
        $scenarioDir = Join-Path $OutDir $scenario
        New-Item -ItemType Directory -Path $scenarioDir -Force | Out-Null
        $csv = Join-Path $scenarioDir "summary.csv"
        $result = Invoke-BenchmarkScenario `
            -RunMode $Mode `
            -UseLargePages ($lp -eq 1) `
            -NumaNode $numa `
            -Label "HFT QPC matrix $scenario" `
            -OutCsv $csv
        $result | Add-Member -NotePropertyName scenario -NotePropertyValue $scenario
        $matrixResults += $result
    }
}

$matrixRows = @()
foreach ($result in $matrixResults) {
    $rows = Import-Csv -Path $result.out_csv
    foreach ($row in $rows) {
        $matrixRows += [PSCustomObject]@{
            scenario = $result.scenario
            shm_large_pages = $result.shm_large_pages
            shm_numa_node = $result.shm_numa_node
            section = $row.section
            run = $row.run
            metric = $row.metric
            count = $row.count
            p50_ns = $row.p50_ns
            p95_ns = $row.p95_ns
            p99_ns = $row.p99_ns
            p999_ns = $row.p999_ns
            max_ns = $row.max_ns
            mean_ns = $row.mean_ns
            pinning = $row.pinning
            exit_code = $row.exit_code
            elapsed_s = $row.elapsed_s
            stderr_log = $row.stderr_log
        }
    }
}

$matrixCsv = Join-Path $OutDir "matrix_summary.csv"
$matrixRows | Export-Csv -Path $matrixCsv -NoTypeInformation -Encoding UTF8
Write-Host "Verified: $matrixCsv" -ForegroundColor Green

$matrixManifest = Join-Path $OutDir "matrix_manifest.json"
$matrixPayload = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = $Mode
    duration_seconds = $DurationSeconds
    enable_shm_qpc = [bool]$EnableShmQpc
    hft_core_index_mode = $CoreIndexMode
    hft_prefetch = $HftPrefetch
    shm_prefetch_next_slot = $ShmPrefetchNextSlot
    engine = $EngineExe
    workdir = $WorkDir
    scenarios = @($matrixResults | ForEach-Object {
        [ordered]@{
            scenario = $_.scenario
            runs = $_.runs
            shm_large_pages = $_.shm_large_pages
            shm_numa_node = $_.shm_numa_node
            out_csv = $_.out_csv
            out_manifest = $_.out_manifest
        }
    })
}
$matrixPayload | ConvertTo-Json -Depth 8 | Set-Content -Path $matrixManifest -Encoding UTF8
Write-Host "Verified: $matrixManifest" -ForegroundColor Green
