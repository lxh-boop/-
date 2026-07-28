param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [string]$OutputRoot = "D:\google\test_results",
    [switch]$Headed,
    [switch]$ReuseRunningServices
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest


function Wait-ComposeServiceHealthy(
    [string]$ComposeFile,
    [string]$Service,
    [string]$LogPath,
    [int]$TimeoutSeconds = 480
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = "not-created"
    while ((Get-Date) -lt $deadline) {
        $containerId = (& docker compose -p stock_daily_app -f $ComposeFile ps -q $Service 2>$null | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($containerId)) {
            $lastState = "container-not-found"
        }
        else {
            $runtimeState = (& docker inspect --format "{{.State.Status}}" $containerId 2>$null | Out-String).Trim()
            $healthState = (& docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $containerId 2>$null | Out-String).Trim()
            $lastState = "runtime=$runtimeState health=$healthState"
            "$(Get-Date -Format s) service=$Service $lastState" | Out-File -LiteralPath $LogPath -Append -Encoding utf8

            if ($healthState -eq "healthy") { return }
            if (($healthState -eq "none") -and ($runtimeState -eq "running")) { return }
            if ($runtimeState -in @("exited", "dead", "removing")) {
                throw "Compose service stopped before becoming healthy: $Service; $lastState"
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "Compose service did not become healthy: $Service; last state: $lastState"
}

function Run-RetryTestCommand(
    [string]$Name,
    [scriptblock]$Command,
    [string]$ResultDir,
    [int]$Attempts = 3,
    [int]$DelaySeconds = 10
) {
    $outputPath = Join-Path $ResultDir ($Name + ".txt")
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        "=== attempt $attempt of $Attempts at $(Get-Date -Format s) ===" |
            Out-File -LiteralPath $outputPath -Append -Encoding utf8
        & $Command *>> $outputPath
        $commandExitCode = $LASTEXITCODE
        "exit_code=$commandExitCode" |
            Out-File -LiteralPath $outputPath -Append -Encoding ascii
        if ($commandExitCode -eq 0) { return }
        if ($attempt -lt $Attempts) { Start-Sleep -Seconds $DelaySeconds }
    }
    throw "Blocking test failed after $Attempts attempts: $Name. See $outputPath"
}

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

function Run-TestCommand([string]$Name, [scriptblock]$Command, [string]$ResultDir) {
    $outputPath = Join-Path $ResultDir ($Name + ".txt")
    & $Command *> $outputPath
    if ($LASTEXITCODE -ne 0) {
        throw "Blocking test failed: $Name. See $outputPath"
    }
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "supervisor_worker_phase_01_$timestamp"
$zipPath = Join-Path $OutputRoot "supervisor_worker_phase_01_$timestamp.zip"
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$configPath = Join-Path $ProjectRoot "local_app_config.json"
$configBackup = Join-Path ([System.IO.Path]::GetTempPath()) "stock_daily_app_phase01_config_$timestamp.json"
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
        Run-TestCommand "01_python_compile" {
            & $pythonExe -m py_compile `
                agent\runtime.py `
                agent\executor.py `
                agent\collaboration\integration.py `
                agent\collaboration\coordinator.py `
                agent\collaboration\runtime_services.py `
                tests\unit\test_supervisor_worker_phase_01_runtime_records.py `
                scripts\refactor\check_supervisor_worker_phase_01.py `
                scripts\refactor\supervisor_worker_phase_01_acceptance.py `
                scripts\refactor\stage6_6_browser_acceptance.py
        } $resultDir

        Run-TestCommand "02_phase_01_unit_tests" {
            & $pythonExe -m pytest tests\unit\test_supervisor_worker_phase_01_runtime_records.py -q
        } $resultDir

        Run-TestCommand "03_runtime_database_tests" {
            & $pythonExe -m pytest tests\unit\test_agent_runtime_persistence.py -q
        } $resultDir

        Run-TestCommand "04_current_worker_regression" {
            & $pythonExe -m pytest tests\unit\test_agent_collaboration_current_workers.py -q
        } $resultDir

        Run-TestCommand "05_atomic_tool_runtime_regression" {
            & $pythonExe -m pytest tests\unit\test_worker_atomic_tool_runtime.py -q
        } $resultDir

        Run-TestCommand "06_combined_phase_gate" {
            & $pythonExe -m pytest `
                tests\unit\test_supervisor_worker_phase_01_runtime_records.py `
                tests\unit\test_agent_runtime_persistence.py `
                tests\unit\test_agent_collaboration_current_workers.py `
                tests\unit\test_worker_atomic_tool_runtime.py `
                -q
        } $resultDir

        Run-TestCommand "07_phase_01_architecture" {
            & $pythonExe scripts\refactor\check_supervisor_worker_phase_01.py
        } $resultDir

        $architectureChecks = @(
            "scripts\refactor\check_stage6_contract.py",
            "scripts\refactor\check_stage6_architecture.py",
            "scripts\refactor\check_stage6_2_architecture.py",
            "scripts\refactor\check_stage6_3_architecture.py",
            "scripts\refactor\check_stage6_4_architecture.py",
            "scripts\refactor\check_stage6_5_architecture.py",
            "scripts\refactor\check_stage6_6_architecture.py"
        )
        foreach ($script in $architectureChecks) {
            if (Test-Path -LiteralPath (Join-Path $ProjectRoot $script)) {
                $name = "architecture_" + ([System.IO.Path]::GetFileNameWithoutExtension($script))
                Run-TestCommand $name { & $pythonExe $script } $resultDir
            }
        }

        if (Test-Path -LiteralPath (Join-Path $ProjectRoot "scripts\refactor\stage4_task_smoke.py")) {
            $taskSmokeDbPath = Join-Path $resultDir "task_smoke.sqlite3"
            Run-TestCommand "08_task_runtime_smoke" {
                & $pythonExe scripts\refactor\stage4_task_smoke.py --db-path $taskSmokeDbPath
            } $resultDir
        }

        Run-TestCommand "09_local_phase_01_acceptance" {
            & $pythonExe scripts\refactor\supervisor_worker_phase_01_acceptance.py --output (Join-Path $resultDir "local_phase_01_acceptance.json")
        } $resultDir

        if (-not $ReuseRunningServices) {
            & docker compose -p stock_daily_app -f $composeFile down --remove-orphans
            & docker compose -p stock_daily_app -f $composeFile config |
                Out-File (Join-Path $resultDir "compose_config.txt") -Encoding utf8
            if ($LASTEXITCODE -ne 0) { throw "Compose configuration validation failed." }

            & docker compose -p stock_daily_app -f $composeFile build api frontend
            if ($LASTEXITCODE -ne 0) { throw "API or frontend image build failed." }

            & docker compose -p stock_daily_app -f $composeFile up -d --remove-orphans --force-recreate api frontend
            if ($LASTEXITCODE -ne 0) { throw "Production Compose startup failed." }
        }

        $healthWaitLog = Join-Path $resultDir "service_health_wait.txt"
        Wait-ComposeServiceHealthy $composeFile "api" $healthWaitLog 480
        Wait-ComposeServiceHealthy $composeFile "frontend" $healthWaitLog 480

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
        Wait-Http "http://127.0.0.1:3000/healthz" 300
        Wait-Http "http://127.0.0.1:3000/api/v1/health" 300
        Start-Sleep -Seconds 5

        $services = & docker compose -p stock_daily_app -f $composeFile config --services
        $services | Out-File (Join-Path $resultDir "compose_services.txt") -Encoding utf8
        $actualServices = @($services | ForEach-Object { [string]$_ } | Where-Object { $_ })
        $serviceKey = (@($actualServices | Sort-Object) -join ",")
        if ($serviceKey -ne "api,frontend") {
            throw "Unexpected production services: $($actualServices -join ', ')"
        }

        Run-TestCommand "10_container_module_import" {
            & docker compose -p stock_daily_app -f $composeFile exec -T api python -c "from agent.collaboration.runtime_services import CollaborationRuntimeServices; from agent.runtime import AgentRuntimeRecorder; print('phase_01_container_import_ok')"
        } $resultDir

        Run-TestCommand "11_container_phase_01_acceptance" {
            & docker compose -p stock_daily_app -f $composeFile exec -T api python scripts/refactor/supervisor_worker_phase_01_acceptance.py --output /app/runtime/phase_01_container_acceptance.json
        } $resultDir
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot "runtime\phase_01_container_acceptance.json")) {
            Copy-Item -LiteralPath (Join-Path $ProjectRoot "runtime\phase_01_container_acceptance.json") -Destination (Join-Path $resultDir "container_phase_01_acceptance.json") -Force
        }

        if (Test-Path -LiteralPath (Join-Path $ProjectRoot "scripts\refactor\stage6_5_browser_acceptance.py")) {
            $browserDir = Join-Path $resultDir "stage6_5_browser_regression"
            New-Item -ItemType Directory -Force -Path $browserDir | Out-Null
            $browserArgs = @(
                "scripts\refactor\stage6_5_browser_acceptance.py",
                "--url", "http://127.0.0.1:3000",
                "--api-url", "http://127.0.0.1:8010",
                "--output-dir", $browserDir
            )
            if ($Headed) { $browserArgs += "--headed" }
            Run-RetryTestCommand "12_stage6_5_browser_regression" {
                & $pythonExe @browserArgs
            } $resultDir 3 10
        }

        if (Test-Path -LiteralPath (Join-Path $ProjectRoot "scripts\refactor\stage6_6_browser_acceptance.py")) {
            $browserDir = Join-Path $resultDir "stage6_6_browser_regression"
            New-Item -ItemType Directory -Force -Path $browserDir | Out-Null
            $browserArgs = @(
                "scripts\refactor\stage6_6_browser_acceptance.py",
                "--url", "http://127.0.0.1:3000",
                "--api-url", "http://127.0.0.1:8010",
                "--output-dir", $browserDir,
                "--regression-result", (Join-Path $resultDir "stage6_5_browser_regression\browser_test_result.json")
            )
            if ($Headed) { $browserArgs += "--headed" }
            Run-RetryTestCommand "13_stage6_6_browser_regression" {
                & $pythonExe @browserArgs
            } $resultDir 3 10
        }

        & git -c core.quotepath=false diff --check -- `
            agent/runtime.py `
            agent/executor.py `
            agent/collaboration/integration.py `
            agent/collaboration/coordinator.py `
            agent/collaboration/runtime_services.py `
            tests/unit/test_supervisor_worker_phase_01_runtime_records.py `
            scripts/refactor/check_supervisor_worker_phase_01.py `
            scripts/refactor/supervisor_worker_phase_01_acceptance.py `
            scripts/refactor/stage6_6_browser_acceptance.py `
            scripts/docker/restart_supervisor_worker_phase_01.ps1 `
            scripts/docker/test_supervisor_worker_phase_01.ps1
        $LASTEXITCODE | Out-File (Join-Path $resultDir "git_diff_check_exit_code.txt") -Encoding ascii
        if ($LASTEXITCODE -ne 0) { throw "git diff --check failed for Phase 01 files." }

        & git -c core.quotepath=false status --short |
            Out-File (Join-Path $resultDir "git_status_after.txt") -Encoding utf8
        & git -c core.quotepath=false diff --stat |
            Out-File (Join-Path $resultDir "git_diff_stat.txt") -Encoding utf8
        & git -c core.quotepath=false diff --name-status |
            Out-File (Join-Path $resultDir "git_diff_name_status.txt") -Encoding utf8
        & git -c core.quotepath=false diff |
            Out-File (Join-Path $resultDir "git_diff.patch") -Encoding utf8
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
            "local_app_config.json restored after Phase 01 acceptance" |
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
