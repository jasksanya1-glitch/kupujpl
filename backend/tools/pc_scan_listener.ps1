# HTTP trigger for Tier A PC scan — called from Piska SP Admin.
param(
    [int]$Port = 8878,
    [string]$BackendRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $BackendRoot) {
    $BackendRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ScriptDir = Join-Path $BackendRoot "tools"
$configEnv = Join-Path $ScriptDir "scan_config.env"
$token = $env:PANEL3_ACCESS_CODE
if (-not $token -and (Test-Path $configEnv)) {
    Get-Content $configEnv | ForEach-Object {
        if ($_ -match '^\s*PANEL3_ACCESS_CODE=(.*)$') { $token = $matches[1].Trim() }
    }
}
if (-not $token) { $token = "1408" }

$log = Join-Path $BackendRoot "tmp\pc_scan_listener.log"
function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format o) $Msg"
    Add-Content -Path $log -Value $line -Encoding UTF8
}

$prefixes = @(
    "http://+:${Port}/",
    "http://127.0.0.1:${Port}/"
)
$listener = New-Object System.Net.HttpListener
foreach ($p in $prefixes) {
    try { $listener.Prefixes.Add($p) } catch { }
}
try {
    $listener.Start()
} catch {
    Write-Log "listener start failed: $($_.Exception.Message) — run install_pc_scan_listener.ps1 as Admin"
    exit 1
}
Write-Log "listening on port $Port"

while ($listener.IsListening) {
    try {
        $ctx = $listener.GetContext()
        $req = $ctx.Request
        $path = $req.Url.AbsolutePath.TrimEnd("/")
        $code = $req.Headers["X-Panel3-Code"]
        $resp = $ctx.Response

        if ($path -eq "/api/health" -and $req.HttpMethod -eq "GET") {
            $body = '{"ok":true,"service":"pc-scan-listener"}'
            $bytes = [Text.Encoding]::UTF8.GetBytes($body)
            $resp.ContentType = "application/json; charset=utf-8"
            $resp.StatusCode = 200
            $resp.OutputStream.Write($bytes, 0, $bytes.Length)
            $resp.Close()
            continue
        }

        if ($path -eq "/api/tier-a/trigger" -and $req.HttpMethod -eq "POST") {
            if ($code -ne $token) {
                $resp.StatusCode = 401
                $resp.Close()
                Write-Log "trigger rejected: bad token from $($req.RemoteEndPoint)"
                continue
            }
            $scanScript = Join-Path $ScriptDir "tier_a_pc_scan.ps1"
            Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
                "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", $scanScript
            )
            Write-Log "trigger OK from $($req.RemoteEndPoint)"
            $body = '{"ok":true,"message":"PC scan started"}'
            $bytes = [Text.Encoding]::UTF8.GetBytes($body)
            $resp.ContentType = "application/json; charset=utf-8"
            $resp.StatusCode = 200
            $resp.OutputStream.Write($bytes, 0, $bytes.Length)
            $resp.Close()
            continue
        }

        $resp.StatusCode = 404
        $resp.Close()
    } catch {
        Write-Log "error: $($_.Exception.Message)"
        Start-Sleep -Milliseconds 200
    }
}
