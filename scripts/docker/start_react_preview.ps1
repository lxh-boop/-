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
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 8
            if ($response.StatusCode -eq 200) { return }
        }
        catch { $lastError = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    throw "服务未在 ${TimeoutSeconds}s 内就绪：$Url；最后错误：$lastError"
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$baseCompose = Join-Path $ProjectRoot "docker-compose.yml"
$previewCompose = Join-Path $ProjectRoot "docker-compose.react-preview.yml"

foreach ($path in @($baseCompose, $previewCompose)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "缺少 Compose 文件：$path" }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "未找到 docker 命令。" }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Engine 当前不可用。" }

Push-Location $ProjectRoot
try {
    Write-Step "校验 Stage 6.1 Compose 叠加配置"
    & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Compose 配置校验失败。" }

    if (-not $NoBuild) {
        Write-Step "构建 React 预览镜像"
        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose build react-preview
        if ($LASTEXITCODE -ne 0) { throw "React 镜像构建失败。" }
    }

    Write-Step "启动 API、Streamlit 与 React Preview"
    & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose up -d --remove-orphans api streamlit react-preview
    if ($LASTEXITCODE -ne 0) { throw "Stage 6.1 Compose 启动失败，请检查 3000/8010/8501 端口。" }

    Wait-Http "http://127.0.0.1:8010/api/v1/health" 300
    Wait-Http "http://127.0.0.1:8501/_stcore/health" 180
    Wait-Http "http://127.0.0.1:3000/healthz" 180

    & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose ps
    Write-Host ""
    Write-Host "React Preview：http://127.0.0.1:3000" -ForegroundColor Green
    Write-Host "Streamlit Baseline：http://127.0.0.1:8501" -ForegroundColor Green
    Write-Host "FastAPI：http://127.0.0.1:8010" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:3000" }
}
finally { Pop-Location }
