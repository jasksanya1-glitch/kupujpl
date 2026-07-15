param(
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
    if (-not $PcHost) { $PcHost = $env:TIER_A_PC_HOST }
    if (-not $PcMac) { $PcMac = $env:TIER_A_PC_MAC }
    if (-not $PcUser) { $PcUser = $env:TIER_A_PC_USER }
}

if (-not $PcHost) {
    Write-Error "Set TIER_A_PC_HOST in tools/scan_config.env"
}

Write-Host "=== Tier A PC-only $(Get-Date -Format o) host=$PcHost ==="

if ($PcMac) {
    & "$ScriptDir\wake_on_lan.ps1" -MacAddress $PcMac
    & "$ScriptDir\wait_for_host.ps1" -HostName $PcHost -TimeoutSec 180
}

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& "$ScriptDir\remote_run_pc_scan.ps1" -HostName $PcHost -SshUser $PcUser -Force
$triggerExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap

if ($triggerExit -ne 0) {
    Write-Error "Tier A PC-only scan was not triggered on $PcHost."
    exit $triggerExit
}

Write-Host "Tier A PC-only scan triggered on $PcHost."
