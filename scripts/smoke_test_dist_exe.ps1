param(
    [string]$ExePath = "$PSScriptRoot\..\dist\StockDailyApp\StockDailyApp.exe",
    [int]$Port = 61250,
    [switch]$OpenBrowser,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

$resolvedExe = (Resolve-Path $ExePath).Path
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$logDir = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stdout = Join-Path $logDir "smoke_dist_stdout.log"
$stderr = Join-Path $logDir "smoke_dist_stderr.log"
Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

Write-Host "Starting packaged EXE without installing:"
Write-Host "  $resolvedExe"
Write-Host "  http://127.0.0.1:$Port"

$process = Start-Process `
    -FilePath $resolvedExe `
    -ArgumentList @("--streamlit-child", "--port", "$Port") `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr

$healthy = $false
for ($i = 0; $i -lt 80; $i++) {
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$Port/_stcore/health" -UseBasicParsing -TimeoutSec 1
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
    }

    if ($process.HasExited) {
        break
    }

    Start-Sleep -Milliseconds 500
}

Write-Host "HEALTH_OK=$healthy"
Write-Host "PID=$($process.Id)"
Write-Host "STDOUT=$stdout"
Write-Host "STDERR=$stderr"

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$Port"
}

if ($KeepRunning) {
    Write-Host "Process is still running. Close it manually or run:"
    Write-Host "  Stop-Process -Id $($process.Id)"
    exit $(if ($healthy) { 0 } else { 1 })
}

if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
}

exit $(if ($healthy) { 0 } else { 1 })
