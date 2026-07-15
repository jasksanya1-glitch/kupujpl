@echo off
schtasks /Create /TN "KupujPL-GentleScanOnce" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\dear2\kupujpl-games\backend\tools\run_gentle_laptop_scan.ps1" /SC ONCE /ST 18:00 /SD 15/06/2026 /F
schtasks /Run /TN "KupujPL-GentleScanOnce"
echo exit %ERRORLEVEL%
