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
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 8
            if ($response.StatusCode -eq 200) { return }
        }
        catch { $lastError = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    throw "Service did not become ready in ${TimeoutSeconds}s: $Url; last error: $lastError"
}

function Assert-Stage62Routes([string]$ApiUrl) {
    $openApi = Invoke-RestMethod -Uri "$ApiUrl/openapi.json" -TimeoutSec 30
    $webPaths = @(
        $openApi.paths.PSObject.Properties |
        Where-Object { $_.Name -like "/api/v1/web/*" }
    )
    if ($webPaths.Count -lt 23) {
        throw "Stage 6.2 API routes are missing: found $($webPaths.Count), expected at least 23."
    }
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "stage_06_2_$timestamp"
$zipPath = Join-Path $OutputRoot "stage_06_2_$timestamp.zip"
$baseCompose = Join-Path $ProjectRoot "docker-compose.yml"
$previewCompose = Join-Path $ProjectRoot "docker-compose.react-preview.yml"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
Start-Transcript -Path (Join-Path $resultDir "test_runner.log") -Force | Out-Null
$exitCode = 0
try {
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Missing project Python: $pythonExe" }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker command was not found." }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine is unavailable." }

    Push-Location $ProjectRoot
    try {
        & $pythonExe -m py_compile application\web_read_service.py server\api\main.py
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe -m pytest tests\unit\test_stage6_2_read_only_web.py -q *> (Join-Path $resultDir "stage6_2_unit_tests.txt")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe scripts\refactor\check_stage6_contract.py *> (Join-Path $resultDir "stage6_contract_check.json")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe scripts\refactor\check_stage6_architecture.py *> (Join-Path $resultDir "stage6_1_architecture_check.json")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe scripts\refactor\check_stage6_2_architecture.py *> (Join-Path $resultDir "stage6_2_architecture_check.json")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose config | Out-File (Join-Path $resultDir "compose_config.txt") -Encoding utf8
        if ($LASTEXITCODE -ne 0) { throw "Compose configuration validation failed." }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose build api react-preview
        if ($LASTEXITCODE -ne 0) { throw "API or React image build failed." }
        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose up -d --remove-orphans --force-recreate api streamlit react-preview
        if ($LASTEXITCODE -ne 0) { throw "Compose startup failed." }

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
        Wait-Http "http://127.0.0.1:8501/_stcore/health" 300
        Wait-Http "http://127.0.0.1:3000/healthz" 300
        Assert-Stage62Routes "http://127.0.0.1:8010"

        $browserArgs = @(
            "scripts\refactor\stage6_2_browser_acceptance.py",
            "--url", "http://127.0.0.1:3000",
            "--api-url", "http://127.0.0.1:8010",
            "--streamlit-url", "http://127.0.0.1:8501",
            "--output-dir", $resultDir
        )
        if ($Headed) { $browserArgs += "--headed" }
        & $pythonExe @browserArgs
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose ps --format json | Out-File (Join-Path $resultDir "compose_ps.jsonl") -Encoding utf8
        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose logs --no-color --timestamps | Out-File (Join-Path $resultDir "compose_logs.txt") -Encoding utf8
    }
    finally { Pop-Location }
}
catch {
    $exitCode = 1
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $resultDir "test_failure.txt") -Encoding UTF8
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $resultDir "*") -DestinationPath $zipPath -Force
    Write-Host "Test results: $zipPath" -ForegroundColor Yellow
}
exit $exitCode
