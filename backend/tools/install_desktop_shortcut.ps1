# Creates a desktop shortcut (UTF-8)
$BackendRoot = Split-Path $PSScriptRoot -Parent
$BatPath = Join-Path $PSScriptRoot "scan_prices.bat"
$Desktop = [Environment]::GetFolderPath("Desktop")
$LinkPath = Join-Path $Desktop "KupujPL - skan tsin.lnk"

if (-not (Test-Path $BatPath)) {
    Write-Error "scan_prices.bat not found"
    exit 1
}

$Wsh = New-Object -ComObject WScript.Shell
$Sc = $Wsh.CreateShortcut($LinkPath)
$Sc.TargetPath = $BatPath
$Sc.WorkingDirectory = $BackendRoot
$Sc.WindowStyle = 1
$Sc.Description = "KupujPL Games - skan tsin z PC (Eneba, G2A, CDKeys) na VPS"
$Sc.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$Sc.Save()

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "Yarlyk stvoreno na Robochomu stoli:"
Write-Host "  $LinkPath"
Write-Host ""
Write-Host "Pered zapuskom: vidredagujte tools\scan_config.env (kod panel3)."
