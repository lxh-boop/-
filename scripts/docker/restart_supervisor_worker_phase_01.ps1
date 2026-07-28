param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [switch]$NoBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}


function Wait-ComposeServiceHealthy(
    [string]$ComposeFile,
    [string]$Service,
    [int]$TimeoutSeconds = 480
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = "not-created"
    while ((Get-Date) -lt $deadline) {
        $containerId = (& docker compose -p stock_daily_app -f $ComposeFile ps -q $Service 2>$null | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($containerId)) {
            $lastState = "container-not-found"
            Start-Sleep -Seconds 2
            continue
        }

        $runtimeState = (& docker inspect --format "{{.State.Status}}" $containerId 2>$null | Out-String).Trim()
        $healthState = (& docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $containerId 2>$null | Out-String).Trim()
        $lastState = "runtime=$runtimeState health=$healthState"
        Write-Host "[$Service] $lastState"

        if ($healthState -eq "healthy") { return }
        if (($healthState -eq "none") -and ($runtimeState -eq "running")) { return }
        if ($runtimeState -in @("exited", "dead", "removing")) {
            throw "Compose service stopped before becoming healthy: $Service; $lastState"
        }
        Start-Sleep -Seconds 2
    }
    throw "Compose service did not become healthy: $Service; last state: $lastState"
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

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) { throw "Missing: $composeFile" }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "local_app_config.json") -PathType Leaf)) {
    throw "Missing local_app_config.json. The launcher never creates or overwrites this sensitive file."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker command was not found." }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { throw "curl.exe was not found." }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Engine is unavailable." }

foreach ($name in @("data", "models", "outputs", "logs", "runtime", "external_repos")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $name) | Out-Null
}

Push-Location $ProjectRoot
try {
    Write-Step "Stop the previous api and frontend containers"
    & docker compose -p stock_daily_app -f $composeFile down --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw "Failed to stop the previous Compose services." }

    Write-Step "Validate production Compose configuration"
    & docker compose -p stock_daily_app -f $composeFile config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Compose configuration validation failed." }

    if (-not $NoBuild) {
        Write-Step "Build FastAPI and React production images"
        & docker compose -p stock_daily_app -f $composeFile build api frontend
        if ($LASTEXITCODE -ne 0) { throw "API or frontend image build failed." }
    }

    Write-Step "Start api + frontend and remove obsolete containers"
    & docker compose -p stock_daily_app -f $composeFile up -d --remove-orphans --force-recreate api frontend
    if ($LASTEXITCODE -ne 0) { throw "Compose startup failed. Check host ports 8010 and 3000." }

    Write-Step "Wait for Docker service health"
    Wait-ComposeServiceHealthy $composeFile "api" 480
    Wait-ComposeServiceHealthy $composeFile "frontend" 480

    Write-Step "Wait for FastAPI and React HTTP health checks"
    Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
    Wait-Http "http://127.0.0.1:3000/healthz" 300
    Wait-Http "http://127.0.0.1:3000/api/v1/health" 300

    Write-Step "Allow the frontend proxy and browser bundle to stabilize"
    Start-Sleep -Seconds 5

    Write-Step "Verify Phase 01 modules inside the restarted API container"
    & docker compose -p stock_daily_app -f $composeFile exec -T api python -c "from agent.collaboration.runtime_services import CollaborationRuntimeServices; from agent.runtime import AgentRuntimeRecorder; print('phase_01_container_import_ok')"
    if ($LASTEXITCODE -ne 0) { throw "Phase 01 module import failed inside the API container." }

    & docker compose -p stock_daily_app -f $composeFile ps
    Write-Host ""
    Write-Host "React:  http://127.0.0.1:3000" -ForegroundColor Green
    Write-Host "FastAPI: http://127.0.0.1:8010" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:3000" }
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    try {
        & docker compose -p stock_daily_app -f $composeFile ps
        & docker compose -p stock_daily_app -f $composeFile logs --no-color --tail 200 api frontend
    }
    catch {}
    throw
}
finally { Pop-Location }
