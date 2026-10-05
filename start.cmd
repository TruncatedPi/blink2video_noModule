@echo off
setlocal
cd /d "%~dp0"

title Blink Connect Server

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON=python.exe"
)

echo ========================================================
echo  Blink Connect Server
echo ========================================================
echo.
echo Stopping any existing server instances...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*serve.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Starting server and opening browser...
echo Press Ctrl+C in this window to stop the server anytime.
echo.

"%PYTHON%" serve.py --open-browser

if %ERRORLEVEL% neq 0 (
    echo.
    echo Server process exited with code %ERRORLEVEL%.
    pause
)
