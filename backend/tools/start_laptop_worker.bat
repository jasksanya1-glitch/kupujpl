@echo off
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set BACKEND_ROOT=%%~fI
cd /d "%BACKEND_ROOT%"
start "" /MIN powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BACKEND_ROOT%\tools\run_gentle_laptop_scan.ps1"
echo Started gentle laptop worker
