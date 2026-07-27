param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [switch]$NoBuild,
    [switch]$NoBrowser
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
        catch { $lastError = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    throw "Service did not become ready: $Url; last error: $lastError"
}

function Assert-Stage64Routes([string]$ApiUrl) {
    $jsonText = & curl.exe --fail --silent --show-error --max-time 30 "$ApiUrl/openapi.json" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Unable to read OpenAPI: $($jsonText | Out-String)" }
    $openApi = ($jsonText | Out-String) | ConvertFrom-Json
    $agentPaths = @($openApi.paths.PSObject.Properties | Where-Object { $_.Name -like "/api/v1/web/agent*" })
    if ($agentPaths.Count -lt 14) { throw "Stage 6.4 Agent routes are missing: $($agentPaths.Count)" }
    Write-Host "Stage 6.4 Agent routes: $($agentPaths.Count)" -ForegroundColor Green
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$baseCompose = Join-Path $ProjectRoot "docker-compose.yml"
$previewCompose = Join-Path $ProjectRoot "docker-compose.react-preview.yml"
foreach ($path in @($baseCompose, $previewCompose)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing Compose file: $path" }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker command was not found." }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { throw "curl.exe was not found." }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Engine is unavailable." }

Push-Location $ProjectRoot
try {
    & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Compose configuration validation failed." }
    if (-not $NoBuild) {
        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose build api react-preview
        if ($LASTEXITCODE -ne 0) { throw "API or React image build failed." }
    }
    & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose up -d --remove-orphans --force-recreate api streamlit react-preview
    if ($LASTEXITCODE -ne 0) { throw "Compose startup failed." }
    Wait-Http "http://127.0.0.1:8010/api/v1/health" 480
    Wait-Http "http://127.0.0.1:8501/_stcore/health" 300
    Wait-Http "http://127.0.0.1:3000/healthz" 300
    Assert-Stage64Routes "http://127.0.0.1:8010"
    & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose ps
    Write-Host "React AI Agent: http://127.0.0.1:3000/agent" -ForegroundColor Green
    Write-Host "Streamlit Baseline: http://127.0.0.1:8501" -ForegroundColor Green
    Write-Host "FastAPI: http://127.0.0.1:8010" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:3000/agent" }
}
finally { Pop-Location }
