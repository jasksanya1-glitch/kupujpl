param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [int]$ListenerPort = 8878
)

$ErrorActionPreference = "SilentlyContinue"

$logPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\tmp\pc_trigger.log"
function Write-TriggerLog([string]$Msg) {
    try {
        "$(Get-Date -Format o) $Msg" | Add-Content -Path $logPath -Encoding UTF8
    } catch { }
}

Write-Host "Stop Tier A PC scan on $HostName"
Write-TriggerLog "stop start host=$HostName"

$code = $env:PANEL3_ACCESS_CODE
if (-not $code) {
    $cfg = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "scan_config.env"
    if (Test-Path $cfg) {
        Get-Content $cfg | ForEach-Object {
            if ($_ -match '^\s*PANEL3_ACCESS_CODE=(.*)$') { $code = $matches[1].Trim() }
        }
    }
}

$stopped = $false
$killed = @()

if ($code) {
    try {
        $uri = "http://${HostName}:${ListenerPort}/api/tier-a/stop"
        $headers = @{ "X-Panel3-Code" = $code }
        $r = Invoke-RestMethod -Uri $uri -Method POST -Headers $headers -Body "" -ContentType "text/plain" -TimeoutSec 15
        if ($r.ok) {
            Write-Host "PC scan stopped via HTTP listener"
            Write-TriggerLog "stop OK http $uri killed=$($r.killed_pids -join ',')"
            $stopped = $true
            if ($r.killed_pids) { $killed = @($r.killed_pids) }
        }
    } catch {
        Write-Host "HTTP stop: $($_.Exception.Message)"
        Write-TriggerLog "stop HTTP fail: $($_.Exception.Message)"
    }
}

if (-not $stopped) {
    Write-Host "PC scan stop via HTTP failed - listener may need restart with /api/tier-a/stop support"
    Write-TriggerLog "stop FAILED http"
}

return @{ ok = $stopped; killed = $killed }
