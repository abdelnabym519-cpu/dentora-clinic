param(
    [int]$RuntimePid = 0,
    [int]$Seconds = 30
)

$ErrorActionPreference = "Stop"

if ($RuntimePid -eq 0) {
    $matches = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match '^python(\.exe)?$' -and
            $_.CommandLine -and
            $_.CommandLine -match 'dentora_voice_runtime[\\/]server\.py'
        }
    if (@($matches).Count -ne 1) {
        throw "Could not identify exactly one Dentora Voice runtime process. Pass -RuntimePid explicitly."
    }
    $RuntimePid = [int]$matches.ProcessId
}

try {
    Get-Process -Id $RuntimePid -ErrorAction Stop | Out-Null
}
catch {
    throw "Runtime PID $RuntimePid is not running."
}

$AllowedRemote = @("127.0.0.1", "::1", "0.0.0.0", "::")
$Violations = @()

Write-Host "Monitoring Dentora Voice runtime PID $RuntimePid for $Seconds seconds..."
Write-Host "During this window, perform one real STT request from the Dentora Voice UI."
Write-Host "This monitor records endpoint metadata only; it does not read audio, transcript, or PHI."

for ($i = 0; $i -lt $Seconds; $i++) {
    $connections = Get-NetTCPConnection -OwningProcess $RuntimePid -ErrorAction SilentlyContinue |
        Where-Object { $_.State -in @("Established", "SynSent", "SynReceived") }

    foreach ($connection in $connections) {
        if ($AllowedRemote -notcontains $connection.RemoteAddress) {
            $Violations += [PSCustomObject]@{
                RemoteAddress = $connection.RemoteAddress
                RemotePort = $connection.RemotePort
                State = $connection.State
            }
        }
    }
    Start-Sleep -Seconds 1
}

if ($Violations.Count -gt 0) {
    Write-Host "FAIL: non-loopback network activity was observed for the Voice runtime process."
    $Violations | Sort-Object RemoteAddress, RemotePort -Unique | Format-Table -AutoSize
    exit 1
}

Write-Host "PASS: no non-loopback TCP connection was observed for Dentora Voice runtime PID $RuntimePid during the monitored STT window."
Write-Host "Optional stronger check: disable Wi-Fi/Ethernet temporarily and repeat the same STT command."
