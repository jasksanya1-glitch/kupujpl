param([string]$BackendRoot = "")

if (-not $BackendRoot) {
    foreach ($p in @(
        "C:\Users\dear2\kupujpl-games\backend",
        "D:\CursorProjects\kupujpl-games\backend"
    )) {
        if (Test-Path (Join-Path $p "tools\scan_config.env")) { $BackendRoot = $p; break }
    }
}
if (-not $BackendRoot) { $BackendRoot = "D:\CursorProjects\kupujpl-games\backend" }

$env:TIER_A_LAPTOP_SHOPS_ONLY = "G2A"
$env:TIER_A_BACKEND_ROOT = $BackendRoot
$env:TIER_A_FORCE_SCAN = "1"
$gentle = Join-Path $BackendRoot "tools\run_gentle_laptop_scan.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $gentle
