$ErrorActionPreference = "Continue"
$root = if (Test-Path "C:\Users\dear2\kupujpl-games\backend") { "C:\Users\dear2\kupujpl-games\backend" } else { "D:\CursorProjects\kupujpl-games\backend" }
$script = Join-Path $root "tools\daily_tier_a_laptop.ps1"
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) -WindowStyle Hidden
Write-Host "Started $script"
