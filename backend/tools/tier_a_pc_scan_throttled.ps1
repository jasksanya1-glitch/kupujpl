# KupujPL PC Tier-A scan with 24h throttle (boot / scheduled).
# Use -Force to bypass the throttle (manual runs).
param(
    [switch]$Force
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptDir
$stampFile = Join-Path $BackendRoot "tmp\tier_a_pc_last_start.json"
$logFile = Join-Path $BackendRoot "tmp\tier_a_pc_boot.log"
$scanPs1 = Join-Path $ScriptDir "tier_a_pc_scan.ps1"
$minHours = 24

function Write-BootLog([string]$msg) {
    $line = "$(Get-Date -Format o) $msg"
    Add-Content -Path $logFile -Value $line -Encoding utf8 -ErrorAction SilentlyContinue
    Write-Host $line
}

New-Item -ItemType Directory -Force -Path (Join-Path $BackendRoot "tmp") | Out-Null

$forceEnv = $env:TIER_A_FORCE_SCAN -match '^(1|true|yes)$'
if (-not $Force -and -not $forceEnv -and (Test-Path $stampFile)) {
    try {
        $stamp = Get-Content $stampFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $started = [datetime]::Parse([string]$stamp.started_at_utc, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
        $ageHours = ((Get-Date).ToUniversalTime() - $started.ToUniversalTime()).TotalHours
        if ($ageHours -lt $minHours) {
            Write-BootLog ("Skip PC scan: last start {0:N1}h ago (< {1}h)" -f $ageHours, $minHours)
            exit 0
        }
    } catch {
        Write-BootLog "Stamp unreadable; continuing: $_"
    }
}

$stampObj = [ordered]@{
    started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    host           = $env:COMPUTERNAME
    user           = $env:USERNAME
    forced         = [bool]($Force -or $forceEnv)
}
($stampObj | ConvertTo-Json) | Set-Content -Path $stampFile -Encoding utf8
Write-BootLog ("Starting PC scan (force={0})" -f $stampObj.forced)

# Boot/scheduled runs bypass VPS pause so a cold start still refreshes offers.
if (-not $env:TIER_A_FORCE_SCAN) { $env:TIER_A_FORCE_SCAN = "1" }
& $scanPs1
$code = $LASTEXITCODE
Write-BootLog "PC scan exit=$code"
exit $code
