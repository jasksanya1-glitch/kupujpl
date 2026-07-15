$ErrorActionPreference = "Continue"
$root = "D:\CursorProjects\kupujpl-games\backend"
$script = Join-Path $root "tools\tier_a_pc_scan.ps1"
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) -WindowStyle Hidden
Write-Host "Started $script"
