# Deploy Tier A scan backend to Piska (192.168.18.15)
param(
    [string]$HostIp = "192.168.18.15",
    [int]$SshPort = 2222,
    [string]$RemoteUser = "dear2",
    [string]$RemoteBackend = "kupujpl-games/backend",
    [string]$LocalBackend = "D:\CursorProjects\kupujpl-games\backend"
)

$ErrorActionPreference = "Stop"
$ssh = "ssh -p $SshPort ${RemoteUser}@${HostIp}"
$scp = "scp -P $SshPort"

Write-Host "=== Deploy Tier A backend to Piska ===" -ForegroundColor Cyan

Invoke-Expression "$ssh `"mkdir C:\Users\dear2\kupujpl-games\backend\tools 2>nul & mkdir C:\Users\dear2\kupujpl-games\backend\tmp 2>nul & mkdir C:\Users\dear2\kupujpl-games\backend\app\parsers 2>nul & mkdir C:\Users\dear2\kupujpl-games\backend\app\core 2>nul`""

$files = @(
    "tools\daily_tier_a_laptop.ps1",
    "tools\tier_a_scan_worker.py",
    "tools\tier_a_pc_scan.ps1",
    "tools\local_offer_worker.py",
    "tools\scan_config.env",
    "tools\wake_on_lan.ps1",
    "tools\wait_for_host.ps1",
    "tools\remote_run_pc_scan.ps1",
    "tools\install_tier_a_laptop_task.bat",
    "requirements.txt"
)

foreach ($f in $files) {
    $src = Join-Path $LocalBackend $f
    if (-not (Test-Path $src)) { throw "Missing $src" }
    $dest = "${RemoteUser}@${HostIp}:${RemoteBackend}/$($f -replace '\\','/')"
    Write-Host "  $f"
    & scp -P $SshPort $src $dest
}

# app/parsers — recursive (exclude __pycache__)
$parsers = Join-Path $LocalBackend "app\parsers"
Get-ChildItem $parsers -File -Recurse | Where-Object { $_.Extension -in @(".py", ".json") } | ForEach-Object {
    $rel = $_.FullName.Substring($parsers.Length).TrimStart("\")
    $remoteDir = "kupujpl-games/backend/app/parsers/$($rel -replace '\\[^\\]+$','')" -replace '\\','/'
    if ($rel -match '\\') {
        Invoke-Expression "$ssh `"mkdir C:\Users\dear2\$($remoteDir -replace '/','\\') 2>nul`"" | Out-Null
    }
    $dest = "${RemoteUser}@${HostIp}:kupujpl-games/backend/app/parsers/$($rel -replace '\\','/')"
    & scp -P $SshPort $_.FullName $dest
}

# app/core minimal
$coreFiles = @("app\core\__init__.py", "app\__init__.py")
foreach ($f in $coreFiles) {
    $src = Join-Path $LocalBackend $f
    if (Test-Path $src) {
        & scp -P $SshPort $src "${RemoteUser}@${HostIp}:kupujpl-games/backend/$($f -replace '\\','/')"
    }
}

Write-Host "`n=== Install Python deps on Piska ===" -ForegroundColor Cyan
Invoke-Expression "$ssh `"cd C:\Users\dear2\kupujpl-games\backend && python -m pip install -q -r requirements.txt 2>nul`""

Write-Host "`n=== Create scheduled task 12:40 ===" -ForegroundColor Cyan
$script = "C:\Users\dear2\kupujpl-games\backend\tools\daily_tier_a_laptop.ps1"
Invoke-Expression "$ssh `"schtasks /Create /TN KupujPL-TierA-Laptop /TR `"powershell.exe -NoProfile -ExecutionPolicy Bypass -File `\"$script`\" -SkipPc`" /SC DAILY /ST 12:40 /F`""

Write-Host "`n=== Update SP Admin config.json ===" -ForegroundColor Cyan
$patchPs1 = @'
$cfgPath = "C:\Users\dear2\laptop-server\sp-admin\config.json"
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$cfg | Add-Member -NotePropertyName tier_a_backend_root -NotePropertyValue "C:\Users\dear2\kupujpl-games\backend" -Force
$cfg | Add-Member -NotePropertyName games_api_url -NotePropertyValue "https://kupujpl.pl/games" -Force
$cfg | Add-Member -NotePropertyName panel3_access_code -NotePropertyValue "1408" -Force
$cfg | Add-Member -NotePropertyName tier_a_pc_host -NotePropertyValue "192.168.18.3" -Force
$cfg | Add-Member -NotePropertyName tier_a_pc_mac -NotePropertyValue "" -Force
$cfg | ConvertTo-Json | Set-Content $cfgPath -Encoding UTF8
Write-Host "config.json updated"
'@
$patchFile = Join-Path $env:TEMP "patch-sp-config.ps1"
Set-Content $patchFile $patchPs1 -Encoding UTF8
& scp -P $SshPort $patchFile "${RemoteUser}@${HostIp}:laptop-server/patch-sp-config.ps1"
Invoke-Expression "$ssh `"powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\dear2\laptop-server\patch-sp-config.ps1`""

Write-Host "`nDone. Backend: C:\Users\dear2\kupujpl-games\backend on Piska" -ForegroundColor Green
Write-Host "Task: KupujPL-TierA-Laptop daily 12:40" -ForegroundColor Green
