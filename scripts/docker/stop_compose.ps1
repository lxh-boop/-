param([string]$ProjectRoot = "D:\stock_daily_app")
$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
if (-not (Test-Path -LiteralPath $composeFile)) { throw "缺少：$composeFile" }
Push-Location $ProjectRoot
try {
    & docker compose -p stock_daily_app -f $composeFile down --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw "停止 Compose 服务失败。" }
    Write-Host "Compose 服务已停止。宿主机 data/models/outputs/logs/runtime 未删除。" -ForegroundColor Green
}
finally { Pop-Location }
