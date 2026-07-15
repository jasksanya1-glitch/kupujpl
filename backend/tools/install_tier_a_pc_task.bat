@echo off
REM Dev PC scan — daily 06:10 Europe/Warsaw, separated from VPS/laptop windows
set TASK_NAME=KupujPL-TierA-PC
set BACKEND=D:\CursorProjects\kupujpl-games\backend
set PYTHON=%BACKEND%\.venv\Scripts\python.exe
set SCRIPT=%BACKEND%\tools\tier_a_pc_scan.ps1
schtasks /Create /TN "%TASK_NAME%" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\"" /SC DAILY /ST 06:10 /F
echo Task %TASK_NAME% OK (uses venv python via tier_a_pc_scan.ps1)
