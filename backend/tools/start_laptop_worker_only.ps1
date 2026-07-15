$ErrorActionPreference = "Continue"
$root = "C:\Users\dear2\kupujpl-games\backend"
$script = Join-Path $root "tools\run_gentle_laptop_scan.ps1"
$running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'tier_a_scan_worker\.py.*laptop' }
if ($running) {
    Write-Host "Worker already running pid $($running.ProcessId)"
    exit 0
}
Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) -WindowStyle Hidden
Write-Host "Started laptop worker"
