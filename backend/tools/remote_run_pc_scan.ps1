param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [string]$TaskName = "KupujPL-TierA-PC",
    [string]$SshUser = $env:TIER_A_PC_USER,
    [int]$ListenerPort = 8878,
    [switch]$Force
)

$ErrorActionPreference = "SilentlyContinue"

$logPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\tmp\pc_trigger.log"
function Write-TriggerLog([string]$Msg) {
    try {
        "$(Get-Date -Format o) $Msg" | Add-Content -Path $logPath -Encoding UTF8
    } catch { }
}

Write-Host "Trigger Tier A PC scan on $HostName (task $TaskName)"
Write-TriggerLog "start host=$HostName"
$started = $false

# 1) HTTP listener on Dev PC (preferred — no schtasks/SSH creds needed)
$code = $env:PANEL3_ACCESS_CODE
if (-not $code) {
    $cfg = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "scan_config.env"
    if (Test-Path $cfg) {
        Get-Content $cfg | ForEach-Object {
            if ($_ -match '^\s*PANEL3_ACCESS_CODE=(.*)$') { $code = $matches[1].Trim() }
        }
    }
}
if ($code) {
  $headers = @{ "X-Panel3-Code" = $code }
  if ($Force) { $headers["X-Tier-A-Force"] = "1" }
  if ($env:TIER_A_PC_SHOPS_ONLY) { $headers["X-Tier-A-Shops"] = $env:TIER_A_PC_SHOPS_ONLY }
  $uris = New-Object System.Collections.Generic.List[string]
  $uris.Add("http://${HostName}:${ListenerPort}/api/tier-a/trigger")
  if ($HostName -notin @("127.0.0.1", "localhost")) {
    $uris.Add("http://127.0.0.1:${ListenerPort}/api/tier-a/trigger")
  }
  foreach ($uri in $uris) {
    if ($started) { break }
    try {
      $r = Invoke-RestMethod -Uri $uri -Method POST -Headers $headers -Body "" -ContentType "text/plain" -TimeoutSec 15
      if ($r.ok -and -not $r.skipped) {
        Write-Host "PC scan triggered via HTTP listener ($uri)"
        Write-TriggerLog "OK http $uri"
        $started = $true
      } elseif ($r.ok -and $r.skipped) {
        Write-Host "HTTP trigger skipped: $($r.message)"
        Write-TriggerLog "HTTP skipped $uri $($r.message)"
      }
    } catch {
      Write-Host "HTTP trigger ($uri): $($_.Exception.Message)"
      Write-TriggerLog "HTTP fail $uri`: $($_.Exception.Message)"
    }
  }
}

# 2) Remote schtasks (needs admin creds on target)
$pcPass = $env:TIER_A_PC_PASSWORD
if (-not $started -and $SshUser -and $pcPass) {
    $out = schtasks /Run /S $HostName /TN $TaskName /U $SshUser /P $pcPass 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PC scan triggered via remote schtasks (credentials)"
        Write-TriggerLog "OK schtasks creds"
        $started = $true
    } else {
        Write-Host "Remote schtasks (cred): $out"
        Write-TriggerLog "schtasks cred fail: $out"
    }
}

if (-not $started) {
    $out = schtasks /Run /S $HostName /TN $TaskName 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PC scan triggered via remote schtasks"
        Write-TriggerLog "OK schtasks anon"
        $started = $true
    } else {
        Write-Host "Remote schtasks: $out"
        Write-TriggerLog "schtasks anon fail: $out"
    }
}

if (-not $started -and $SshUser) {
    $sshArgs = @(
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=accept-new",
        "${SshUser}@${HostName}",
        "schtasks /Run /TN `"$TaskName`""
    )
    $sshOut = & ssh @sshArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PC scan triggered via SSH"
        Write-TriggerLog "OK ssh"
        $started = $true
    } else {
        Write-Host "SSH trigger failed: $sshOut"
        Write-TriggerLog "ssh fail: $sshOut"
    }
}

if (-not $started) {
    Write-Host "PC scan not triggered - install pc_scan_listener on Dev PC (tools/install_pc_scan_listener.ps1)"
    Write-TriggerLog "FAILED all methods"
    exit 1
}
exit 0
