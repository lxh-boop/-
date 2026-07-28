$ErrorActionPreference = "Stop"

$Root = "D:\stock_daily_app"
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
Set-Location -LiteralPath $Root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Missing project Python: $PythonExe"
}

& $PythonExe -m scheduler.scheduler_cli run --all-users --source scheduled
exit $LASTEXITCODE
