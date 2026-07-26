param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [string]$OutputRoot = "D:\google\test_results",
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 300) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $output = & curl.exe --fail --silent --show-error --max-time 8 $Url 2>&1
            if ($LASTEXITCODE -eq 0) { return }
            $lastError = ($output | Out-String).Trim()
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "Service did not become ready: $Url; last error: $lastError"
}

function Assert-Stage63Routes([string]$ApiUrl) {
    $jsonText = & curl.exe --fail --silent --show-error --max-time 30 "$ApiUrl/openapi.json" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read OpenAPI: $($jsonText | Out-String)"
    }
    $openApi = ($jsonText | Out-String) | ConvertFrom-Json
    $paperPaths = @(
        $openApi.paths.PSObject.Properties |
        Where-Object { $_.Name -like "/api/v1/web/paper-trading*" }
    )
    if ($paperPaths.Count -lt 13) {
        throw "Stage 6.3 paper-trading routes are missing: $($paperPaths.Count)"
    }
}

function Save-ComposeDiagnostics(
    [string]$ProjectRoot,
    [string]$BaseCompose,
    [string]$PreviewCompose,
    [string]$ResultDir
) {
    try {
        Push-Location $ProjectRoot
        & docker compose -p stock_daily_app -f $BaseCompose -f $PreviewCompose ps --format json |
            Out-File (Join-Path $ResultDir "compose_ps.jsonl") -Encoding utf8
        & docker compose -p stock_daily_app -f $BaseCompose -f $PreviewCompose logs --no-color --timestamps |
            Out-File (Join-Path $ResultDir "compose_logs.txt") -Encoding utf8
    }
    catch {
        $_ | Out-String | Set-Content -LiteralPath (
            Join-Path $ResultDir "compose_diagnostics_error.txt"
        ) -Encoding UTF8
    }
    finally {
        try { Pop-Location } catch {}
    }
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "stage_06_3_$timestamp"
$zipPath = Join-Path $OutputRoot "stage_06_3_$timestamp.zip"
$baseCompose = Join-Path $ProjectRoot "docker-compose.yml"
$previewCompose = Join-Path $ProjectRoot "docker-compose.react-preview.yml"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
Start-Transcript -Path (Join-Path $resultDir "test_runner.log") -Force | Out-Null
$exitCode = 0

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Missing project Python: $pythonExe"
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker command was not found."
    }
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        throw "curl.exe was not found."
    }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Engine is unavailable."
    }

    Push-Location $ProjectRoot
    try {
        & $pythonExe -m py_compile `
            application\web_paper_trading_service.py `
            server\api\main.py `
            server\api\routers\web_paper_trading.py `
            server\task_runtime\handlers.py `
            scripts\refactor\stage6_3_browser_acceptance.py
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & $pythonExe -m pytest `
            tests\unit\test_stage6_2_read_only_web.py `
            tests\unit\test_stage6_3_paper_trading_web.py `
            -q *> (Join-Path $resultDir "stage6_3_unit_tests.txt")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $contractCheckPath = Join-Path $resultDir "stage6_contract_check.json"
        & $pythonExe scripts\refactor\check_stage6_contract.py *> $contractCheckPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $stage61CheckPath = Join-Path $resultDir "stage6_1_architecture_check.json"
        & $pythonExe scripts\refactor\check_stage6_architecture.py *> $stage61CheckPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $stage62CheckPath = Join-Path $resultDir "stage6_2_architecture_check.json"
        & $pythonExe scripts\refactor\check_stage6_2_architecture.py *> $stage62CheckPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $stage63CheckPath = Join-Path $resultDir "stage6_3_architecture_check.json"
        & $pythonExe scripts\refactor\check_stage6_3_architecture.py *> $stage63CheckPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $taskSmokeDbPath = Join-Path $resultDir "task_smoke.sqlite3"
        $taskSmokeResultPath = Join-Path $resultDir "task_runtime_smoke.json"
        & $pythonExe scripts\refactor\stage4_task_smoke.py `
            --db-path $taskSmokeDbPath *> $taskSmokeResultPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose config |
            Out-File (Join-Path $resultDir "compose_config.txt") -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            throw "Compose configuration validation failed."
        }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose build api react-preview
        if ($LASTEXITCODE -ne 0) {
            throw "API or React image build failed."
        }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose `
            up -d --remove-orphans --force-recreate api streamlit react-preview
        if ($LASTEXITCODE -ne 0) {
            throw "Compose startup failed."
        }

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
        Wait-Http "http://127.0.0.1:8501/_stcore/health" 300
        Wait-Http "http://127.0.0.1:3000/healthz" 300
        Assert-Stage63Routes "http://127.0.0.1:8010"

        $browserArgs = @(
            "scripts\refactor\stage6_3_browser_acceptance.py",
            "--url", "http://127.0.0.1:3000",
            "--api-url", "http://127.0.0.1:8010",
            "--streamlit-url", "http://127.0.0.1:8501",
            "--output-dir", $resultDir
        )
        if ($Headed) { $browserArgs += "--headed" }

        $browserConsole = Join-Path $resultDir "browser_acceptance_console.txt"
        & $pythonExe @browserArgs 2>&1 | Tee-Object -FilePath $browserConsole
        $browserExitCode = $LASTEXITCODE
        if ($browserExitCode -ne 0) {
            $exitCode = 1
            if (-not (Test-Path -LiteralPath (Join-Path $resultDir "acceptance_report.md"))) {
                "Browser acceptance exited with code $browserExitCode before producing its report." |
                    Set-Content -LiteralPath (
                        Join-Path $resultDir "browser_acceptance_missing_report.txt"
                    ) -Encoding UTF8
            }
        }
    }
    finally {
        Pop-Location
    }
}
catch {
    $exitCode = 1
    $_ | Out-String | Set-Content -LiteralPath (
        Join-Path $resultDir "test_failure.txt"
    ) -Encoding UTF8
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Save-ComposeDiagnostics $ProjectRoot $baseCompose $previewCompose $resultDir
    try { Stop-Transcript | Out-Null } catch {}
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $resultDir "*") -DestinationPath $zipPath -Force
    Write-Host "Test results: $zipPath" -ForegroundColor Yellow
}

exit $exitCode
