@echo off
setlocal

cd /d D:\stock_daily_app

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if exist "D:\stock_daily_app\.venv1\Scripts\python.exe" (
  set "PYTHON_EXE=D:\stock_daily_app\.venv1\Scripts\python.exe"
) else (
  set "PYTHON_EXE=C:\Users\86195\AppData\Local\Programs\Python\Python312\python.exe"
)

"%PYTHON_EXE%" ^
  -m scheduler.scheduler_cli run ^
  --all-users ^
  --source scheduled

exit /b %ERRORLEVEL%
