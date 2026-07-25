param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [int]$Tail = 300,
    [switch]$Follow
)
$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
if (-not (Test-Path -LiteralPath $composeFile)) { throw "缺少：$composeFile" }
Push-Location $ProjectRoot
try {
    if ($Follow) {
        & docker compose -p stock_daily_app -f $composeFile logs --tail $Tail -f
    }
    else {
        & docker compose -p stock_daily_app -f $composeFile logs --tail $Tail
    }
}
finally { Pop-Location }
