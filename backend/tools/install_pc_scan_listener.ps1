# Run once on Dev PC as Administrator (firewall + logon task).
$ErrorActionPreference = "Stop"
$root = "D:\CursorProjects\kupujpl-games\backend"
$listenerPy = Join-Path $root "tools\pc_scan_listener.py"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$port = 8878
$taskName = "KupujPL-TierA-PC-Listener"

Write-Host "=== Firewall rule (port $port) ===" -ForegroundColor Cyan
$rule = Get-NetFirewallRule -DisplayName "KupujPL PC Scan Listener" -ErrorAction SilentlyContinue
if (-not $rule) {
    try {
        New-NetFirewallRule -DisplayName "KupujPL PC Scan Listener" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Any | Out-Null
        Write-Host "  Added firewall rule" -ForegroundColor Green
    } catch {
        Write-Host "  Firewall rule skipped: run as Administrator if remote trigger cannot connect" -ForegroundColor Yellow
    }
} else {
    Write-Host "  Rule exists" -ForegroundColor Green
}

Write-Host "=== Scheduled task $taskName (At logon) ===" -ForegroundColor Cyan
$tr = "`"$python`" -u `"$listenerPy`""
cmd /c "schtasks /Delete /TN `"$taskName`" /F >nul 2>nul"
$created = $false
schtasks /Create /TN $taskName /TR $tr /SC ONLOGON /RL HIGHEST /F | Out-Host
if ($LASTEXITCODE -eq 0) {
    $created = $true
} else {
    Write-Host "  Highest task failed; trying current-user logon task" -ForegroundColor Yellow
    schtasks /Create /TN $taskName /TR $tr /SC ONLOGON /F | Out-Host
    if ($LASTEXITCODE -eq 0) { $created = $true }
}
if (-not $created) {
    Write-Host "  Scheduled task was not created; listener will still start for this session" -ForegroundColor Yellow
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    [string]$_.CommandLine -like "*pc_scan_listener.py*"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Process -FilePath $python -ArgumentList @("-u", $listenerPy) -WindowStyle Hidden -WorkingDirectory $root
Start-Sleep -Seconds 2
try {
    $r = Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 3
    Write-Host "Health OK: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "Health check failed: $_" -ForegroundColor Yellow
}

Write-Host "Done. Piska: POST http://192.168.18.5:$port/api/tier-a/trigger (X-Panel3-Code)" -ForegroundColor Green
