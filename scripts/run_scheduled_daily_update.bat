@echo off
setlocal

set "ROOT=D:\stock_daily_app"
set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"

cd /d "%ROOT%"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Missing project Python: %PYTHON_EXE%
  exit /b 2
)

"%PYTHON_EXE%" -m scheduler.scheduler_cli run --all-users --source scheduled
exit /b %ERRORLEVEL%
