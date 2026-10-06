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
"%PYTHON%" blink2video.py stop
if errorlevel 1 (
    echo Could not stop the existing application. See the message above.
    pause
    exit /b 1
)

echo Starting server and opening browser...
echo Press Ctrl+C in this window to stop the server anytime.
echo.

"%PYTHON%" blink2video.py serve --open-browser

if %ERRORLEVEL% neq 0 (
    echo.
    echo Server process exited with code %ERRORLEVEL%.
    pause
)
