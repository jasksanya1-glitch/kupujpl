# Install Netdata on Windows laptop for Tier A scan monitoring (localhost only — no VPS streaming)
param(
    [string]$BackendRoot = "D:\CursorProjects\kupujpl-games\backend"
)

$ErrorActionPreference = "Stop"

Write-Host "Installing Netdata via winget..."
winget install --id Netdata.Netdata -e --accept-source-agreements --accept-package-agreements

Set-Service -Name Netdata -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service Netdata -ErrorAction SilentlyContinue

$goD = Join-Path $env:ProgramFiles "netdata\etc\netdata\go.d"
$conf = Join-Path $BackendRoot "deploy\netdata-laptop\tierascan-laptop.conf"
if (Test-Path $conf) {
    Copy-Item $conf (Join-Path $goD "tierascan-laptop.conf") -Force
    Write-Host "Copied go.d config to $goD"
}

Write-Host "Netdata UI: http://localhost:19999"
Write-Host "Set PANEL3_ACCESS_CODE in Netdata service env for VPS poll."
