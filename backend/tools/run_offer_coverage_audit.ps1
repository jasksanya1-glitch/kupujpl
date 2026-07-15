param(
    [int]$Limit = 200,
    [int]$Skip = 0,
    [int]$Parallel = 2,
    [ValidateSet("db", "api")]
    [string]$Mode = "api",
    [string]$Tier = "top5000",
    [string]$Shops = "Steam,Instant Gaming,Kinguin,CDKeys,G2A,Gamivo,GOG,Epic Games",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptDir

$configEnv = Join-Path $ScriptDir "scan_config.env"
if (Test-Path $configEnv) {
    Get-Content $configEnv -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $k = $matches[1].Trim()
            $v = $matches[2].Trim()
            if ($v -and -not (Get-Item -Path "Env:$k" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:$k" -Value $v
            }
        }
    }
}

$env:OFFER_SCAN_DISABLED_SHOPS = (($env:OFFER_SCAN_DISABLED_SHOPS, "Eneba") -join ",")

$python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Missing venv python: $python"
}

$argsList = @(
    (Join-Path $BackendRoot "scripts\audit_offer_coverage.py"),
    "--mode", $Mode,
    "--tier", $Tier,
    "--limit", [string]$Limit,
    "--skip", [string]$Skip,
    "--parallel", [string]$Parallel,
    "--shops", $Shops
)
if ($Apply) {
    $argsList += "--apply"
}

Set-Location $BackendRoot
& $python @argsList
exit $LASTEXITCODE
