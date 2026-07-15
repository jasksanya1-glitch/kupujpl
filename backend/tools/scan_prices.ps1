# KupujPL — local price scan (home PC -> VPS)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BackendRoot = Split-Path $PSScriptRoot -Parent
$ConfigPath = Join-Path $PSScriptRoot "scan_config.env"
$ExamplePath = Join-Path $PSScriptRoot "scan_config.example.env"
$Worker = Join-Path $PSScriptRoot "local_offer_worker.py"
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

function Read-DotEnv {
    param([string]$Path)
    $vars = @{}
    if (-not (Test-Path $Path)) { return $vars }
    foreach ($raw in Get-Content $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { continue }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim()
        if ($val.Length -ge 2 -and $val.StartsWith('"') -and $val.EndsWith('"')) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $vars[$key] = $val
    }
    return $vars
}

Write-Host ""
Write-Host "  KupujPL Games - skan tsin z PC" -ForegroundColor Cyan
Write-Host "  ===============================" -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-Path $ConfigPath)) {
    Write-Host "  Fayl scan_config.env ne znaydeno." -ForegroundColor Yellow
    if (Test-Path $ExamplePath) {
        Copy-Item $ExamplePath $ConfigPath
        Write-Host "  Stvoreno tools\scan_config.env - vkazhit PANEL3_ACCESS_CODE." -ForegroundColor Yellow
        Start-Process notepad.exe $ConfigPath
        Read-Host "  Pislya zberezhennya natysnit Enter"
    } else {
        Write-Host "  Stvorit tools\scan_config.env (dyt. scan_config.example.env)" -ForegroundColor Red
        Read-Host "  Enter"
        exit 1
    }
}

$cfg = Read-DotEnv -Path $ConfigPath
$apiUrl = if ($cfg["GAMES_API_URL"]) { $cfg["GAMES_API_URL"] } else { "https://kupujpl.pl/games" }
$code = $cfg["PANEL3_ACCESS_CODE"]
if (-not $code -or $code -match "^(vas_?kod|ваш_код)" ) {
    Write-Host "  U scan_config.env ne zadano PANEL3_ACCESS_CODE (kod vid panel3)." -ForegroundColor Red
    Start-Process notepad.exe $ConfigPath
    Read-Host "  Enter"
    exit 1
}

$limit = if ($cfg["SCAN_LIMIT"]) { $cfg["SCAN_LIMIT"] } else { "60" }
$parallel = if ($cfg["SCAN_PARALLEL"]) { $cfg["SCAN_PARALLEL"] } else { "8" }
$shops = if ($cfg["SCAN_SHOPS"]) { $cfg["SCAN_SHOPS"] } else { "Kinguin,GOG,Epic Games,Eneba,G2A,CDKeys" }
$delay = if ($cfg["SCAN_DELAY"]) { $cfg["SCAN_DELAY"] } else { "0" }

$env:GAMES_API_URL = $apiUrl.TrimEnd("/")
$env:PANEL3_ACCESS_CODE = $code
foreach ($key in @("OFFER_FETCH_FAST", "ENEBA_SLUG_DELAY_SEC", "HTTP_FETCH_TIMEOUT", "SCAN_CYCLE_PAUSE", "SCAN_IDLE_PAUSE")) {
    if ($cfg[$key]) { Set-Item -Path "env:$key" -Value $cfg[$key] }
}
if (-not $env:OFFER_FETCH_FAST) { $env:OFFER_FETCH_FAST = "1" }

Set-Location $BackendRoot

$pyExe = $null
if (Test-Path $VenvPython) {
    $pyExe = $VenvPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pyExe = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pyExe = "py"
}

if (-not $pyExe) {
    Write-Host "  Python ne znaydeno. Vstanovit Python 3.12+ abo venv u backend\.venv" -ForegroundColor Red
    Read-Host "  Enter"
    exit 1
}

Write-Host "  Python: $pyExe" -ForegroundColor DarkGray
Write-Host "  API:    $env:GAMES_API_URL" -ForegroundColor Gray
Write-Host "  Magazyny: $shops" -ForegroundColor Gray
Write-Host "  Paket:  $limit ihor, parallel=$parallel, delay=${delay}s" -ForegroundColor Gray
Write-Host "  Ctrl+C - zupynyty" -ForegroundColor DarkGray
Write-Host ""

$workerArgs = @(
    $Worker,
    "--limit", $limit,
    "--parallel", $parallel,
    "--delay", $delay,
    "--shops", $shops
)

$exitCode = 0
try {
    if ($pyExe -eq "py") {
        & py @workerArgs
    } else {
        & $pyExe @workerArgs
    }
    if ($null -ne $LASTEXITCODE) { $exitCode = $LASTEXITCODE }
} catch {
    Write-Host ""
    Write-Host "  Pomylka: $_" -ForegroundColor Red
    $exitCode = 1
}

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "  Gotovo." -ForegroundColor Green
} else {
    Write-Host "  Zaversheno z kodom $exitCode" -ForegroundColor Yellow
}
Read-Host "  Enter dlya zakrittya"
exit $exitCode
