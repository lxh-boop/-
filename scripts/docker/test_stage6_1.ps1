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
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "stage_06_1_$timestamp"
$zipPath = Join-Path $OutputRoot "stage_06_1_$timestamp.zip"
$baseCompose = Join-Path $ProjectRoot "docker-compose.yml"
$previewCompose = Join-Path $ProjectRoot "docker-compose.react-preview.yml"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
Start-Transcript -Path (Join-Path $resultDir "test_runner.log") -Force | Out-Null
$exitCode = 0

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "缺少项目 Python：$pythonExe" }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "未找到 docker 命令。" }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine 当前不可用。" }

    Push-Location $ProjectRoot
    try {
        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose config | Out-File (Join-Path $resultDir "compose_config.txt") -Encoding utf8
        if ($LASTEXITCODE -ne 0) { throw "Compose 配置校验失败。" }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose up -d --build --remove-orphans api streamlit react-preview
        if ($LASTEXITCODE -ne 0) { throw "Compose 构建或启动失败。" }

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 420
        Wait-Http "http://127.0.0.1:8501/_stcore/health" 240
        Wait-Http "http://127.0.0.1:3000/healthz" 240

        & $pythonExe "scripts\refactor\check_stage5_architecture.py" *> (Join-Path $resultDir "stage5_architecture_check.json")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe "scripts\refactor\check_stage6_contract.py" *> (Join-Path $resultDir "stage6_contract_check.json")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe "scripts\refactor\check_stage6_architecture.py" *> (Join-Path $resultDir "stage6_architecture_check.json")
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $browserArgs = @(
            "scripts\refactor\stage6_1_browser_acceptance.py",
            "--url", "http://127.0.0.1:3000",
            "--api-url", "http://127.0.0.1:8010",
            "--streamlit-url", "http://127.0.0.1:8501",
            "--output-dir", $resultDir
        )
        if ($Headed) { $browserArgs += "--headed" }
        & $pythonExe @browserArgs
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose ps --format json | Out-File (Join-Path $resultDir "compose_ps.jsonl") -Encoding utf8
        & docker compose -p stock_daily_app -f $baseCompose -f $previewCompose logs --no-color --timestamps | Out-File (Join-Path $resultDir "compose_logs.txt") -Encoding utf8
        & docker inspect stock_daily_app-api-1 stock_daily_app-streamlit-1 stock_daily_app-react-preview-1 | Out-File (Join-Path $resultDir "docker_inspect.json") -Encoding utf8
    }
    finally { Pop-Location }
}
catch {
    $exitCode = 1
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $resultDir "test_failure.txt") -Encoding UTF8
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $resultDir "*") -DestinationPath $zipPath -Force
    Write-Host "测试结果：$zipPath" -ForegroundColor Yellow
}

exit $exitCode
