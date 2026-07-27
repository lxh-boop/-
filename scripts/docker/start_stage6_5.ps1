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

    Write-Step "Wait for FastAPI and React health checks"
    Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
    Wait-Http "http://127.0.0.1:3000/healthz" 300

    & docker compose -p stock_daily_app -f $composeFile ps
    Write-Host ""
    Write-Host "React:  http://127.0.0.1:3000" -ForegroundColor Green
    Write-Host "FastAPI: http://127.0.0.1:8010" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:3000" }
}
finally { Pop-Location }
