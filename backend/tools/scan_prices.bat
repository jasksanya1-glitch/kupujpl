@echo off
chcp 65001 >nul 2>&1
title KupujPL - skan tsin
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scan_prices.ps1"
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
    echo.
    echo Pomylka zapusku. Kod: %ERR%
    pause
)
exit /b %ERR%
