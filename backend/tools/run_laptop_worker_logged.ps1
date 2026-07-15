$ErrorActionPreference = "Continue"
$root = "C:\Users\dear2\kupujpl-games\backend"
$log = Join-Path $root "tmp\tier_a_gentle_worker.log"
Set-Location $root
Get-Content tools\scan_config.env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        $k = $matches[1].Trim(); $v = $matches[2].Trim()
        if ($v) { Set-Item -Path "Env:$k" -Value $v }
    }
}
"=== start $(Get-Date -Format o) ===" | Add-Content -Path $log -Encoding utf8
python -u tools\tier_a_scan_worker.py --worker laptop --parallel 4 *>> $log 2>&1
"=== exit $LASTEXITCODE $(Get-Date -Format o) ===" | Add-Content -Path $log -Encoding utf8
