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

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 240) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 8
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "服务未在 ${TimeoutSeconds}s 内就绪：$Url；最后错误：$lastError"
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "项目目录不存在：$ProjectRoot"
}

$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    throw "缺少 docker-compose.yml：$composeFile"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "local_app_config.json") -PathType Leaf)) {
    throw "缺少 local_app_config.json。Compose 不会创建或覆盖该敏感配置文件。"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 docker 命令，请先安装并启动 Docker Desktop。"
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine 当前不可用，请启动 Docker Desktop。"
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "当前 Docker 不支持 docker compose。"
}

foreach ($name in @("data", "models", "outputs", "logs", "runtime", "external_repos")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $name) | Out-Null
}

Push-Location $ProjectRoot
try {
    Write-Step "校验 Compose 配置"
    & docker compose -p stock_daily_app -f $composeFile config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose config 校验失败。"
    }

    if (-not $NoBuild) {
        Write-Step "构建 API 与 Streamlit 镜像"
        & docker compose -p stock_daily_app -f $composeFile build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker 镜像构建失败。"
        }
    }

    Write-Step "启动 Compose 服务"
    & docker compose -p stock_daily_app -f $composeFile up -d --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose 启动失败。请检查 8010/8501 端口是否被本地进程占用。"
    }

    Write-Step "等待 FastAPI 与 Streamlit 健康检查"
    Wait-Http "http://127.0.0.1:8010/api/v1/health" 300
    Wait-Http "http://127.0.0.1:8501/_stcore/health" 180

    & docker compose -p stock_daily_app -f $composeFile ps

    Write-Host ""
    Write-Host "FastAPI：http://127.0.0.1:8010" -ForegroundColor Green
    Write-Host "Streamlit：http://127.0.0.1:8501" -ForegroundColor Green

    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:8501"
    }
}
finally {
    Pop-Location
}
