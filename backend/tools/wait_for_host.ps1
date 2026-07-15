param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [int]$TimeoutSec = 180,
    [int]$IntervalSec = 5
)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-Connection -ComputerName $HostName -Count 1 -Quiet -ErrorAction SilentlyContinue) {
        Write-Host "$HostName is online"
        exit 0
    }
    Start-Sleep -Seconds $IntervalSec
}
Write-Error "Timeout waiting for $HostName"
