param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [string]$OutputRoot = "D:\google\test_results",
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 600) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        $command = 'curl.exe --fail --silent --show-error --max-time 8 "' + $Url + '" 2>&1'
        $output = & cmd.exe /d /c $command
        $code = $LASTEXITCODE
        if ($code -eq 0) { return }
        $lastError = "curl exit code ${code}: $(($output | Out-String).Trim())"
        Start-Sleep -Seconds 2
    }
    throw "Service did not become ready: $Url; last error: $lastError"
}

function Save-ComposeDiagnostics([string]$Root, [string]$ComposeFile, [string]$ResultDir) {
    try {
        Push-Location $Root
        & docker compose -p stock_daily_app -f $ComposeFile ps --format json |
            Out-File (Join-Path $ResultDir "compose_ps.jsonl") -Encoding utf8
        & docker compose -p stock_daily_app -f $ComposeFile logs --no-color --timestamps |
            Out-File (Join-Path $ResultDir "compose_logs.txt") -Encoding utf8
    }
    catch {
        $_ | Out-String | Set-Content -LiteralPath (Join-Path $ResultDir "compose_diagnostics_error.txt") -Encoding UTF8
    }
    finally {
        try { Pop-Location } catch {}
    }
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "stage_06_7_$timestamp"
$zipPath = Join-Path $OutputRoot "stage_06_7_$timestamp.zip"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
Start-Transcript -Path (Join-Path $resultDir "test_runner.log") -Force | Out-Null
$exitCode = 0

try {
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "Missing project Python: $pythonExe" }
    if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) { throw "Missing Compose file: $composeFile" }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker command was not found." }
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { throw "curl.exe was not found." }

    Push-Location $ProjectRoot
    try {
        & $pythonExe -m py_compile `
            local_config.py `
            scheduler\runtime_scheduler.py `
            scheduler\daily_worker.py `
            scheduler\scheduler_cli.py `
            scheduler\health_check.py `
            scheduler\windows_task_installer.py `
            scheduler_manager.py `
            server\api\main.py `
            application\web_settings_service.py `
            application\paper_profile_service.py `
            server\api\schemas\settings.py `
            server\api\routers\web_settings.py `
            scripts\refactor\check_stage6_7_architecture.py `
            scripts\refactor\stage6_7_scheduler_acceptance.py
        if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }

        $unitPath = Join-Path $resultDir "stage6_7_unit_tests.txt"
        & $pythonExe -m pytest `
            tests\unit\test_stage6_7_persistent_scheduler.py `
            tests\unit\test_scheduler_cli.py `
            tests\unit\test_scheduled_daily_worker.py `
            tests\unit\test_scheduled_public_task_once.py `
            tests\unit\test_windows_task_scripts.py `
            tests\unit\test_stage6_6_market_config.py `
            -q *> $unitPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $archPath = Join-Path $resultDir "stage6_7_architecture_check.json"
        & $pythonExe scripts\refactor\check_stage6_7_architecture.py *> $archPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $composeFile config --quiet
        if ($LASTEXITCODE -ne 0) { throw "Compose configuration validation failed." }
        & docker compose -p stock_daily_app -f $composeFile build api frontend
        if ($LASTEXITCODE -ne 0) { throw "API or frontend image build failed." }
        & docker compose -p stock_daily_app -f $composeFile up -d --remove-orphans --force-recreate api frontend
        if ($LASTEXITCODE -ne 0) { throw "Compose startup failed." }

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 600
        Wait-Http "http://127.0.0.1:3000/healthz" 300
        Wait-Http "http://127.0.0.1:8010/api/v1/web/settings" 300

        $browserArgs = @(
            "scripts\refactor\stage6_7_scheduler_acceptance.py",
            "--url", "http://127.0.0.1:3000",
            "--api-url", "http://127.0.0.1:8010",
            "--output-dir", $resultDir
        )
        if ($Headed) { $browserArgs += "--headed" }
        $consolePath = Join-Path $resultDir "browser_acceptance_console.txt"
        & $pythonExe @browserArgs 2>&1 | Tee-Object -FilePath $consolePath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $composeFile config --services |
            Out-File (Join-Path $resultDir "compose_services.txt") -Encoding utf8
    }
    finally { Pop-Location }
}
catch {
    $exitCode = 1
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $resultDir "test_failure.txt") -Encoding UTF8
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Save-ComposeDiagnostics $ProjectRoot $composeFile $resultDir
    try { Stop-Transcript | Out-Null } catch {}
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $resultDir "*") -DestinationPath $zipPath -Force
    Write-Host "Test results: $zipPath" -ForegroundColor Yellow
}

exit $exitCode
