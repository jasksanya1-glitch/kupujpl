@echo off
REM Install Windows Task Scheduler: Tier A laptop scan daily at 12:40 Europe/Warsaw
set TASK_NAME=KupujPL-TierA-Laptop
set SCRIPT=D:\CursorProjects\kupujpl-games\backend\tools\daily_tier_a_laptop.ps1

schtasks /Create /TN "%TASK_NAME%" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT%\" -SkipPc" /SC DAILY /ST 12:40 /F
echo Task %TASK_NAME% created for 12:40 daily.
