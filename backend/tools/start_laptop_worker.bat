@echo off
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set BACKEND_ROOT=%%~fI
cd /d "%BACKEND_ROOT%"
wscript.exe //B "%SCRIPT_DIR%run_ps1_hidden.vbs" "%BACKEND_ROOT%\tools\run_gentle_laptop_scan.ps1"
echo Started gentle laptop worker
