param(
    [int]$Port = 8501,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$logDir = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stdout = Join-Path $logDir "local_streamlit_stdout.log"
$stderr = Join-Path $logDir "local_streamlit_stderr.log"
Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

Write-Host "Starting source Streamlit app:"
Write-Host "  $projectRoot"
Write-Host "  http://127.0.0.1:$Port"

$process = Start-Process `
    -FilePath "py" `
    -ArgumentList @(
        "-m", "streamlit", "run", "app.py",
        "--server.address", "127.0.0.1",
        "--server.port", "$Port",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false"
    ) `
    -WorkingDirectory $projectRoot `
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

exit $(if ($healthy) { 0 } else { 1 })
