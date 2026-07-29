param(
    [string]$ExePath = "$PSScriptRoot\..\dist\StockDailyApp\StockDailyApp.exe",
    [string]$FrontendUrl = "http://127.0.0.1:3000"
)

$ErrorActionPreference = "Stop"
$resolvedExe = (Resolve-Path $ExePath).Path

& $resolvedExe --dry-run --url $FrontendUrl
if ($LASTEXITCODE -ne 0) { throw "Packaged React launcher dry-run failed." }

$response = Invoke-WebRequest ($FrontendUrl.TrimEnd('/') + '/healthz') -UseBasicParsing -TimeoutSec 5
if ($response.StatusCode -ne 200) { throw "Production React frontend is not healthy: $FrontendUrl" }

Write-Host "Packaged launcher and production React frontend are healthy." -ForegroundColor Green
