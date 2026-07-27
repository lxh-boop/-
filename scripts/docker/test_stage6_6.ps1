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
        $command = 'curl.exe --fail --silent --show-error --max-time 8 "' + $Url + '" 2>&1'
        $output = & cmd.exe /d /c $command
        $curlExitCode = $LASTEXITCODE
        if ($curlExitCode -eq 0) { return }
        $lastError = "curl exit code ${curlExitCode}: $(($output | Out-String).Trim())"
        Start-Sleep -Seconds 2
    }
    throw "Service did not become ready: $Url; last error: $lastError"
}

function Save-ComposeDiagnostics([string]$ProjectRoot, [string]$ComposeFile, [string]$ResultDir) {
    $pushed = $false
    try {
        Push-Location $ProjectRoot
        $pushed = $true
        & docker compose -p stock_daily_app -f $ComposeFile ps --format json |
            Out-File (Join-Path $ResultDir "compose_ps.jsonl") -Encoding utf8
        & docker compose -p stock_daily_app -f $ComposeFile logs --no-color --timestamps |
            Out-File (Join-Path $ResultDir "compose_logs.txt") -Encoding utf8
        & docker inspect stock_daily_app-api-1 stock_daily_app-frontend-1 |
            Out-File (Join-Path $ResultDir "docker_inspect.json") -Encoding utf8
    }
    catch {
        $_ | Out-String | Set-Content -LiteralPath (Join-Path $ResultDir "compose_diagnostics_error.txt") -Encoding UTF8
    }
    finally { if ($pushed) { Pop-Location } }
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "stage_06_6_$timestamp"
$zipPath = Join-Path $OutputRoot "stage_06_6_$timestamp.zip"
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$configPath = Join-Path $ProjectRoot "local_app_config.json"
$configBackup = Join-Path ([System.IO.Path]::GetTempPath()) "stock_daily_app_stage66_config_$timestamp.json"
$configBackedUp = $false

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
Start-Transcript -Path (Join-Path $resultDir "test_runner.log") -Force | Out-Null
$exitCode = 0

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Missing project Python: $pythonExe" }
    if (-not (Test-Path -LiteralPath $composeFile)) { throw "Missing Compose file: $composeFile" }
    if (-not (Test-Path -LiteralPath $configPath)) { throw "Missing local_app_config.json" }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker command was not found." }
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { throw "curl.exe was not found." }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine is unavailable." }

    Copy-Item -LiteralPath $configPath -Destination $configBackup -Force
    $configBackedUp = $true

    foreach ($name in @("data", "models", "outputs", "logs", "runtime", "external_repos")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $name) | Out-Null
    }

    Push-Location $ProjectRoot
    try {
        & $pythonExe -m py_compile `
            local_config.py `
            data_tushare.py `
            core\llm\profiles.py `
            application\web_read_service.py `
            application\web_settings_service.py `
            server\api\schemas\settings.py `
            server\api\presenters\settings.py `
            server\api\routers\web_settings.py `
            scripts\refactor\check_stage6_2_architecture.py `
            scripts\refactor\check_stage6_6_architecture.py `
            scripts\refactor\stage6_6_browser_acceptance.py
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $unitPath = Join-Path $resultDir "stage6_6_unit_tests.txt"
        & $pythonExe -m pytest `
            tests\unit\test_stage6_2_read_only_web.py `
            tests\unit\test_stage6_3_paper_trading_web.py `
            tests\unit\test_stage6_4_agent_web.py `
            tests\unit\test_stage6_5_cutover.py `
            tests\unit\test_stage6_6_market_config.py `
            tests\unit\test_file_loaders.py `
            tests\unit\test_backtest_display.py `
            -q *> $unitPath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $checks = @(
            @("stage6_contract_check.json", "scripts\refactor\check_stage6_contract.py"),
            @("stage6_1_architecture_check.json", "scripts\refactor\check_stage6_architecture.py"),
            @("stage6_2_architecture_check.json", "scripts\refactor\check_stage6_2_architecture.py"),
            @("stage6_3_architecture_check.json", "scripts\refactor\check_stage6_3_architecture.py"),
            @("stage6_4_architecture_check.json", "scripts\refactor\check_stage6_4_architecture.py"),
            @("stage6_5_architecture_check.json", "scripts\refactor\check_stage6_5_architecture.py"),
            @("stage6_6_architecture_check.json", "scripts\refactor\check_stage6_6_architecture.py")
        )
        foreach ($check in $checks) {
            $resultPath = Join-Path $resultDir $check[0]
            & $pythonExe $check[1] *> $resultPath
            if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        }

        $taskSmokeDbPath = Join-Path $resultDir "task_smoke.sqlite3"
        $taskSmokePath = Join-Path $resultDir "task_runtime_smoke.json"
        & $pythonExe scripts\refactor\stage4_task_smoke.py --db-path $taskSmokeDbPath *> $taskSmokePath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $composeFile down --remove-orphans
        & docker compose -p stock_daily_app -f $composeFile config |
            Out-File (Join-Path $resultDir "compose_config.txt") -Encoding utf8
        if ($LASTEXITCODE -ne 0) { throw "Compose configuration validation failed." }

        & docker compose -p stock_daily_app -f $composeFile build api frontend
        if ($LASTEXITCODE -ne 0) { throw "API or frontend image build failed." }

        & docker compose -p stock_daily_app -f $composeFile up -d --remove-orphans --force-recreate api frontend
        if ($LASTEXITCODE -ne 0) { throw "Production Compose startup failed." }

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
        Wait-Http "http://127.0.0.1:3000/healthz" 300
        Wait-Http "http://127.0.0.1:3000/api/v1/health" 300

        $services = & docker compose -p stock_daily_app -f $composeFile config --services
        $services | Out-File (Join-Path $resultDir "compose_services.txt") -Encoding utf8
        $actualServices = @($services | ForEach-Object { [string]$_ } | Where-Object { $_ })
        $serviceKey = (@($actualServices | Sort-Object) -join ",")
        if ($serviceKey -ne "api,frontend") {
            throw "Unexpected production services: $($actualServices -join ', ')"
        }

        $regressionDir = Join-Path $resultDir "stage6_5_regression"
        New-Item -ItemType Directory -Force -Path $regressionDir | Out-Null
        $regressionArgs = @(
            "scripts\refactor\stage6_5_browser_acceptance.py",
            "--url", "http://127.0.0.1:3000",
            "--api-url", "http://127.0.0.1:8010",
            "--output-dir", $regressionDir
        )
        if ($Headed) { $regressionArgs += "--headed" }
        $regressionConsole = Join-Path $regressionDir "browser_acceptance_console.txt"
        & $pythonExe @regressionArgs 2>&1 | Tee-Object -FilePath $regressionConsole
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $browserArgs = @(
            "scripts\refactor\stage6_6_browser_acceptance.py",
            "--url", "http://127.0.0.1:3000",
            "--api-url", "http://127.0.0.1:8010",
            "--output-dir", $resultDir,
            "--regression-result", (Join-Path $regressionDir "browser_test_result.json")
        )
        if ($Headed) { $browserArgs += "--headed" }
        $browserConsole = Join-Path $resultDir "browser_acceptance_console.txt"
        & $pythonExe @browserArgs 2>&1 | Tee-Object -FilePath $browserConsole
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
    }
    finally { Pop-Location }
}
catch {
    $exitCode = 1
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $resultDir "test_failure.txt") -Encoding UTF8
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if ($configBackedUp -and (Test-Path -LiteralPath $configBackup)) {
        try {
            Copy-Item -LiteralPath $configBackup -Destination $configPath -Force
            Remove-Item -LiteralPath $configBackup -Force
            "local_app_config.json restored after acceptance" |
                Set-Content -LiteralPath (Join-Path $resultDir "config_restore_status.txt") -Encoding UTF8
        }
        catch {
            $exitCode = 1
            $_ | Out-String | Set-Content -LiteralPath (Join-Path $resultDir "config_restore_error.txt") -Encoding UTF8
        }
    }
    Save-ComposeDiagnostics $ProjectRoot $composeFile $resultDir
    try { Stop-Transcript | Out-Null } catch {}
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $resultDir "*") -DestinationPath $zipPath -Force
    Write-Host "Test results: $zipPath" -ForegroundColor Yellow
}

exit $exitCode
