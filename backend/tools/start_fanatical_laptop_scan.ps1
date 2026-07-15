param(
    [string]$BackendRoot = ""
)

if (-not $BackendRoot) {
    foreach ($p in @(
        "C:\Users\dear2\kupujpl-games\backend",
        "D:\CursorProjects\kupujpl-games\backend"
    )) {
        if (Test-Path (Join-Path $p "tools\scan_config.env")) { $BackendRoot = $p; break }
    }
}
if (-not $BackendRoot) { $BackendRoot = "D:\CursorProjects\kupujpl-games\backend" }

$ErrorActionPreference = "Continue"
Set-Location $BackendRoot

$config = Join-Path $BackendRoot "tools\scan_config.env"
if (Test-Path $config) {
    Get-Content $config | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $k = $matches[1].Trim()
            $v = $matches[2].Trim()
            if ($v) { Set-Item -Path "Env:$k" -Value $v }
        }
    }
}

$env:TIER_A_FORCE_SCAN = "1"
$env:TIER_A_LAPTOP_SHOPS_ONLY = "Fanatical"
$env:TIER_A_LAPTOP_PARALLEL = "8"
$env:PANEL3_ACCESS_CODE = if ($env:PANEL3_ACCESS_CODE) { $env:PANEL3_ACCESS_CODE } else { "1408" }
$env:GAMES_API_URL = if ($env:GAMES_API_URL) { $env:GAMES_API_URL } else { "https://kupujpl.pl/games" }

$python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "Refreshing Fanatical Awin feed..."
& $python scripts\refresh_affiliate_feeds.py
if ($LASTEXITCODE -ne 0) { Write-Warning "Feed refresh exit $LASTEXITCODE (may use cache)" }

Write-Host "Starting Fanatical Tier A scan (laptop worker)..."
& (Join-Path $BackendRoot "tools\start_laptop_worker.bat")
Write-Host "Done - tail log: tmp\tier_a_gentle_worker.log"
