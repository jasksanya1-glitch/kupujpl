param(
    [string]$ApiUrl = $env:GAMES_API_URL,
    [string]$Panel3Code = $env:PANEL3_ACCESS_CODE,
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

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$configEnv = Join-Path $ScriptDir "scan_config.env"
if (Test-Path $configEnv) {
    Get-Content $configEnv | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $k = $matches[1].Trim()
            $v = $matches[2].Trim()
            if (-not (Get-Item -Path "Env:$k" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:$k" -Value $v
            }
        }
    }
    if (-not $ApiUrl) { $ApiUrl = $env:GAMES_API_URL }
    if (-not $Panel3Code) { $Panel3Code = $env:PANEL3_ACCESS_CODE }
}

if (-not $ApiUrl) { $ApiUrl = "https://kupujpl.pl/games" }
if (-not $Panel3Code) {
    Write-Error "Set PANEL3_ACCESS_CODE (tools/scan_config.env)"
}

function Wait-ListReady {
    param([int]$TimeoutSec = 7200)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $headers = @{ "X-Panel3-Code" = $Panel3Code }
            $status = Invoke-RestMethod -Uri "$ApiUrl/api/admin/tier-a/status" -Headers $headers -TimeoutSec 30
            if ($status.list_ready) {
                Write-Host "list_ready=true version=$($status.list_version)"
                return $true
            }
        } catch {
            Write-Host "Waiting for list_ready: $_"
        }
        Start-Sleep -Seconds 15
    }
    return $false
}

Write-Host "=== Tier A laptop-only $(Get-Date -Format o) ==="

if (-not (Wait-ListReady)) {
    Write-Error "Timeout waiting for tier A list_ready"
}

Set-Location $BackendRoot
$env:GAMES_API_URL = $ApiUrl
$env:PANEL3_ACCESS_CODE = $Panel3Code
$env:ENEBA_SLUG_DELAY_SEC = "0.5"
$env:TIER_A_LAPTOP_PARALLEL = "4"
$env:TIER_A_G2A_PARALLEL = "1"
$env:G2A_REQUEST_DELAY_SEC = "8.0"
$env:G2A_403_COOLDOWN_SEC = "120"
$env:G2A_403_MAX_COOLDOWN_SEC = "180"
$env:G2A_PHASE_PAUSE_SEC = "300"

& "$ScriptDir\start_laptop_worker.bat"

Write-Host "Tier A laptop-only scan started (Kinguin, then G2A)."
