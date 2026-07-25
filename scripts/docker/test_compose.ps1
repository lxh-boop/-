param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [string]$OutputRoot = "D:\google\test_results",
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 240) {
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

function Invoke-Json([string]$Method, [string]$Url, [object]$Body = $null) {
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Url -TimeoutSec 30
    }
    return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 20) -TimeoutSec 30
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultDir = Join-Path $OutputRoot "stage_05_$timestamp"
$zipPath = Join-Path $OutputRoot "stage_05_$timestamp.zip"
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
$transcriptPath = Join-Path $resultDir "test_runner.log"
Start-Transcript -Path $transcriptPath -Force | Out-Null
$exitCode = 0

try {
    if (-not (Test-Path -LiteralPath $composeFile)) { throw "缺少：$composeFile" }
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "缺少项目 Python：$pythonExe" }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "未找到 docker 命令。" }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Engine 当前不可用。" }

    foreach ($name in @("data", "models", "outputs", "logs", "runtime", "external_repos")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $name) | Out-Null
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "local_app_config.json"))) {
        throw "缺少 local_app_config.json。"
    }

    Push-Location $ProjectRoot
    try {
        & docker compose -p stock_daily_app -f $composeFile down --remove-orphans
        & docker compose -p stock_daily_app -f $composeFile config | Out-File -FilePath (Join-Path $resultDir "compose_config.txt") -Encoding utf8
        if ($LASTEXITCODE -ne 0) { throw "Compose 配置校验失败。" }

        & docker compose -p stock_daily_app -f $composeFile up -d --build --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw "Compose 构建或启动失败。" }

        Wait-Http "http://127.0.0.1:8010/api/v1/health" 420
        Wait-Http "http://127.0.0.1:8501/_stcore/health" 240

        & docker compose -p stock_daily_app -f $composeFile ps --format json | Out-File -FilePath (Join-Path $resultDir "compose_ps_before.jsonl") -Encoding utf8

        # Verify a container write reaches the protected host runtime bind mount.
        $probeName = "stage5_mount_probe_$timestamp.json"
        & docker compose -p stock_daily_app -f $composeFile exec -T api python -c "from pathlib import Path; import json; p=Path('/app/runtime/$probeName'); p.write_text(json.dumps({'success': True}), encoding='utf-8'); print(p)"
        if ($LASTEXITCODE -ne 0) { throw "无法在 API 容器中写入 runtime 探针。" }
        $hostProbe = Join-Path $ProjectRoot "runtime\$probeName"
        if (-not (Test-Path -LiteralPath $hostProbe -PathType Leaf)) { throw "runtime 绑定挂载未落到宿主机：$hostProbe" }
        Copy-Item -LiteralPath $hostProbe -Destination (Join-Path $resultDir "runtime_mount_probe.json") -Force

        # Submit a long task, restart the API container, and verify the persisted task becomes interrupted.
        $submit = Invoke-Json "POST" "http://127.0.0.1:8010/api/v1/tasks" @{
            task_type = "diagnostic.sleep"
            args = @()
            kwargs = @{ seconds = 60; steps = 120 }
            owner_id = "stage5_acceptance"
            session_id = "restart-recovery"
            metadata = @{ surface = "compose" }
            timeout_seconds = 120
            max_retries = 0
        }
        $taskId = [string]$submit.data.task_id
        if (-not $taskId) { throw "未获得重启恢复测试 task_id。" }
        Start-Sleep -Seconds 2
        & docker compose -p stock_daily_app -f $composeFile restart api
        if ($LASTEXITCODE -ne 0) { throw "API 容器重启失败。" }
        Wait-Http "http://127.0.0.1:8010/api/v1/health" 180
        $recovered = Invoke-Json "GET" "http://127.0.0.1:8010/api/v1/tasks/$taskId"
        $recoveryStatus = [string]$recovered.data.status
        @{
            success = ($recoveryStatus -eq "interrupted")
            task_id = $taskId
            status = $recoveryStatus
        } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $resultDir "restart_recovery.json") -Encoding UTF8

        $stage4ArchitecturePath = Join-Path $resultDir "stage4_architecture_check.json"
        $stage5ArchitecturePath = Join-Path $resultDir "stage5_architecture_check.json"
        & $pythonExe "scripts\refactor\check_stage4_architecture.py" *> $stage4ArchitecturePath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }
        & $pythonExe "scripts\refactor\check_stage5_architecture.py" *> $stage5ArchitecturePath
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        $browserArgs = @(
            "scripts\refactor\stage5_browser_acceptance.py",
            "--url", "http://127.0.0.1:8501",
            "--api-url", "http://127.0.0.1:8010",
            "--output-dir", $resultDir,
            "--project-root", $ProjectRoot,
            "--deep-agent-check"
        )
        if ($Headed) { $browserArgs += "--headed" }
        & $pythonExe @browserArgs
        if ($LASTEXITCODE -ne 0) { $exitCode = 1 }

        & docker compose -p stock_daily_app -f $composeFile ps --format json | Out-File -FilePath (Join-Path $resultDir "compose_ps_after.jsonl") -Encoding utf8
        & docker compose -p stock_daily_app -f $composeFile logs --no-color --timestamps | Out-File -FilePath (Join-Path $resultDir "compose_logs.txt") -Encoding utf8
        & docker inspect stock_daily_app-api-1 stock_daily_app-streamlit-1 | Out-File -FilePath (Join-Path $resultDir "docker_inspect.json") -Encoding utf8
    }
    finally {
        Pop-Location
    }
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
