param(
    [switch]$Bootstrap,
    [switch]$SkipPc,
    [string]$ApiUrl = $env:GAMES_API_URL,
    [string]$Panel3Code = $env:PANEL3_ACCESS_CODE,
    [string]$PcHost = $env:TIER_A_PC_HOST,
    [string]$PcMac = $env:TIER_A_PC_MAC,
    [string]$PcUser = $env:TIER_A_PC_USER,
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
    if (-not $PcHost) { $PcHost = $env:TIER_A_PC_HOST }
    if (-not $PcMac) { $PcMac = $env:TIER_A_PC_MAC }
    if (-not $PcUser) { $PcUser = $env:TIER_A_PC_USER }
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

Write-Host "=== Tier A laptop orchestrator $(Get-Date -Format o) ==="

function Test-RecentTierAScan {
    param([int]$Hours = 10)
    try {
        $headers = @{ "X-Panel3-Code" = $Panel3Code }
        $status = Invoke-RestMethod -Uri "$ApiUrl/api/admin/tier-a/status" -Headers $headers -TimeoutSec 30
        $cutoff = (Get-Date).ToUniversalTime().AddHours(-$Hours)
        # This orchestrator is responsible for local workers only. The VPS run
        # starts first, so treating it as a recent run incorrectly skips PC/laptop.
        foreach ($key in @("laptop", "pc")) {
            $w = $status.$key
            if (-not $w) { continue }
            $phase = [string]$w.phase
            if ($phase -in @("scan_keyshops", "scan_cdkeys")) { return $true }
            if ($phase -ne "done") { continue }
            $raw = [string]$w.finished_at
            if (-not $raw) { continue }
            try {
                $ts = [datetime]::Parse($raw.Replace("Z", ""))
                if ($ts -ge $cutoff) { return $true }
            } catch { }
            }
    } catch {
        Write-Host "Recent-scan check failed: $_"
    }
    return $false
}

if (-not $Bootstrap) {
    function Test-AutoScanPaused {
        try {
            $headers = @{ "X-Panel3-Code" = $Panel3Code }
            $status = Invoke-RestMethod -Uri "$ApiUrl/api/admin/tier-a/status" -Headers $headers -TimeoutSec 30
            if ($status.auto_scan_paused) { return $true }
        } catch {
            Write-Host "Auto-scan pause check (API) failed: $_"
        }
        $pauseFile = Join-Path $BackendRoot "tmp\tier_a_auto_scan_paused.json"
        if (Test-Path $pauseFile) {
            try {
                $p = Get-Content $pauseFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($p.paused) { return $true }
            } catch { }
        }
        return $false
    }
    if (Test-AutoScanPaused) {
        Write-Host "Skip laptop orchestrator — auto scan paused by admin"
        exit 0
    }
    $minHours = if ($env:TIER_A_MIN_HOURS_BETWEEN_RUNS) { [int]$env:TIER_A_MIN_HOURS_BETWEEN_RUNS } else { 10 }
    if (Test-RecentTierAScan -Hours $minHours) {
        Write-Host "Skip laptop orchestrator — Tier A run within last ${minHours}h"
        exit 0
    }
}

if (-not (Wait-ListReady)) {
    Write-Error "Timeout waiting for tier A list_ready"
}

if (-not $SkipPc -and $PcMac -and $PcHost) {
    & "$ScriptDir\wake_on_lan.ps1" -MacAddress $PcMac
    & "$ScriptDir\wait_for_host.ps1" -HostName $PcHost -TimeoutSec 180
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & "$ScriptDir\remote_run_pc_scan.ps1" -HostName $PcHost
    $ErrorActionPreference = $prevEap
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

Write-Host "Tier A gentle laptop scan started."
