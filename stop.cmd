@echo off
setlocal
cd /d "%~dp0"

title Stopping Blink Connect

echo ========================================================
echo  Stopping Blink Connect Server
echo ========================================================
echo.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*serve.py*' -or $_.CommandLine -like '*blink2video*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Server stopped.
ping 127.0.0.1 -n 2 >nul
