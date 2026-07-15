$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Split-Path -Parent $ScriptDir

$configEnv = Join-Path $ScriptDir "scan_config.env"
if (Test-Path $configEnv) {
    Get-Content $configEnv | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $k = $matches[1].Trim()
            $v = $matches[2].Trim()
            if ($v -and -not (Get-Item -Path "Env:$k" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:$k" -Value $v
            }
        }
    }
}

Set-Location $BackendRoot
if (-not $env:GAMES_API_URL) { $env:GAMES_API_URL = "https://kupujpl.pl/games" }
if (-not $env:PANEL3_ACCESS_CODE) {
    Write-Error "Set PANEL3_ACCESS_CODE in tools/scan_config.env"
}

$pauseFile = Join-Path $BackendRoot "tmp\tier_a_auto_scan_paused.json"
$forceScan = $env:TIER_A_FORCE_SCAN -match '^(1|true|yes)$'
if (-not $forceScan) {
    if (Test-Path $pauseFile) {
        try {
            $p = Get-Content $pauseFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($p.paused) {
                Write-Host "Skip PC scan - auto scan paused (local file)"
                exit 0
            }
        } catch { }
    }
    try {
        $headers = @{ "X-Panel3-Code" = $env:PANEL3_ACCESS_CODE }
        $status = Invoke-RestMethod -Uri "$($env:GAMES_API_URL)/api/admin/tier-a/status" -Headers $headers -TimeoutSec 20
        if ($status.auto_scan_paused) {
            Write-Host "Skip PC scan - auto scan paused (VPS)"
            exit 0
        }
    } catch {
        Write-Host "Auto-scan pause check (API) failed: $_"
    }
} else {
    Write-Host "Manual PC scan (TIER_A_FORCE_SCAN) - bypass auto-scan pause"
}

$extraArgs = @()
if ($env:TIER_A_PC_SHOPS_ONLY) {
    $extraArgs += @("--shops", $env:TIER_A_PC_SHOPS_ONLY)
}
if ($env:TIER_A_SIZE) {
    $extraArgs += @("--limit", $env:TIER_A_SIZE)
}

$python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Missing venv python: $python"
}

& $python "$ScriptDir\tier_a_scan_worker.py" --worker pc --parallel 6 @extraArgs
exit $LASTEXITCODE
