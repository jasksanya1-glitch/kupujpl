$ErrorActionPreference = "Continue"
$root = if ($env:TIER_A_BACKEND_ROOT) { $env:TIER_A_BACKEND_ROOT }
        elseif (Test-Path "C:\Users\dear2\kupujpl-games\backend") { "C:\Users\dear2\kupujpl-games\backend" }
        else { "D:\CursorProjects\kupujpl-games\backend" }
$log = Join-Path $root "tmp\tier_a_gentle_worker.log"
Set-Location $root

$config = Join-Path $root "tools\scan_config.env"
if (Test-Path $config) {
    Get-Content $config | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $k = $matches[1].Trim()
            $v = $matches[2].Trim()
            if ($v) { Set-Item -Path "Env:$k" -Value $v }
        }
    }
}

$env:GAMES_API_URL = if ($env:GAMES_API_URL) { $env:GAMES_API_URL.Trim() } else { "https://kupujpl.pl/games" }
$env:TIER_A_LAPTOP_PARALLEL = "4"
$env:TIER_A_G2A_PARALLEL = "1"
$env:G2A_REQUEST_DELAY_SEC = "8.0"
$env:G2A_403_COOLDOWN_SEC = "120"
$env:G2A_403_MAX_COOLDOWN_SEC = "180"
$env:G2A_PHASE_PAUSE_SEC = "300"
$env:G2A_MAX_PRODUCT_TRIES = "2"
$env:G2A_FEED_ONLY = "1"

$shopArgs = @()
if ($env:TIER_A_LAPTOP_SHOPS_ONLY) {
    $shopArgs += @("--shops", $env:TIER_A_LAPTOP_SHOPS_ONLY)
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

"=== gentle start $(Get-Date -Format o) shops=$($env:TIER_A_LAPTOP_SHOPS_ONLY) ===" | Add-Content -Path $log -Encoding utf8
& $python -u tools\tier_a_scan_worker.py --worker laptop --parallel 4 @shopArgs *>> $log 2>&1
"=== gentle exit $LASTEXITCODE $(Get-Date -Format o) ===" | Add-Content -Path $log -Encoding utf8
