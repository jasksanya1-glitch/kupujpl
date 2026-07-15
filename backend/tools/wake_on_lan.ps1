param(
    [Parameter(Mandatory = $true)]
    [string]$MacAddress,
    [string]$Broadcast = "255.255.255.255",
    [int]$Port = 9
)

$mac = ($MacAddress -replace '[:\-\.]', '').ToUpper()
if ($mac.Length -ne 12) {
    Write-Error "Invalid MAC address: $MacAddress"
}

$packet = [byte[]](,0xFF * 6)
for ($i = 0; $i -lt 6; $i++) {
    $packet += [byte]::Parse($mac.Substring($i * 2, 2), [System.Globalization.NumberStyles]::HexNumber)
}

$udp = New-Object System.Net.Sockets.UdpClient
$udp.Connect($Broadcast, $Port)
[void]$udp.Send($packet, $packet.Length)
$udp.Close()
Write-Host "WoL magic packet sent to $MacAddress"
