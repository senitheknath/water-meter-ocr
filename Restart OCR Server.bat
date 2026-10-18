@echo off
setlocal
title Restart Water Meter OCR Server
cd /d "%~dp0"

echo Stopping the previous OCR server...
powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

where py >nul 2>nul
if %errorlevel% equ 0 (
    start "Water Meter OCR Backend" /min py -3 -u upload_server.py
    goto :started
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    start "Water Meter OCR Backend" /min python -u upload_server.py
    goto :started
)

echo Python was not found.
pause
exit /b 1

:started
echo OCR server restarted. Calculate Bill will capture, flip horizontally,
echo read only the four grey digits, and update Firebase.
timeout /t 3 >nul
