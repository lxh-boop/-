$ErrorActionPreference = "Stop"

$Root = "D:\stock_daily_app"
Set-Location -LiteralPath $Root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$VenvPython = Join-Path $Root ".venv1\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = "C:\Users\86195\AppData\Local\Programs\Python\Python312\python.exe"
}

& $PythonExe -m scheduler.scheduler_cli run --all-users --source scheduled
exit $LASTEXITCODE
