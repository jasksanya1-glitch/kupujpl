$ErrorActionPreference = "Continue"
$root = if (Test-Path "C:\Users\dear2\kupujpl-games\backend") {
    "C:\Users\dear2\kupujpl-games\backend"
} else {
    "D:\CursorProjects\kupujpl-games\backend"
}
Set-Location $root
Get-Content tools\scan_config.env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        $k = $matches[1].Trim(); $v = $matches[2].Trim()
        if ($v) { Set-Item -Path "Env:$k" -Value $v }
    }
}
& python tools\tier_a_scan_worker.py --worker laptop --parallel 8
