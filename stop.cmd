@echo off
setlocal
cd /d "%~dp0"

title Stopping Blink Connect

echo ========================================================
echo  Stopping Blink Connect Server
echo ========================================================
echo.
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON=python.exe"
)

"%PYTHON%" blink2video.py stop
if errorlevel 1 (
    echo The application could not be fully stopped. See the message above.
    pause
    exit /b 1
)

echo Server stopped.
ping 127.0.0.1 -n 2 >nul
