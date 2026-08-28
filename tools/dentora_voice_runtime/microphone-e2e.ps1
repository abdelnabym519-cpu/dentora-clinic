param(
    [string]$UiUrl = "http://localhost:3000",
    [string]$RuntimeUrl = "http://127.0.0.1:8765",
    [string]$BackendUrl = "http://127.0.0.1:8100"
)

$ErrorActionPreference = "Stop"

function Require-Http([string]$Url, [string]$Name) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            throw "$Name returned HTTP $($response.StatusCode)"
        }
    }
    catch {
        throw "$Name is not reachable at $Url. $($_.Exception.Message)"
    }
}

Require-Http "$RuntimeUrl/health" "Dentora Voice local runtime"
Require-Http "$BackendUrl/health" "Dentora backend"
Require-Http "$UiUrl/login" "Dentora UI"

Write-Host "Dentora Voice microphone E2E preflight passed."
Write-Host "1. Log in to Dentora in the browser."
Write-Host "2. Open the Dentora Voice panel."
Write-Host "3. Click Start and allow microphone permission."
Write-Host "4. Speak a synthetic/non-PHI validation command."
Write-Host "5. Click Stop."
Write-Host "6. Observe: LISTENING -> PROCESSING -> EXECUTING -> final state."
Write-Host "7. Verify the expected patient/context/UI action in Dentora."
Write-Host "This uses the existing browser path: Microphone -> local faster-whisper -> transcript -> /voice/execute -> ToolRegistry -> UI."
Write-Host "No audio or transcript is written by this PowerShell script."

Start-Process "$UiUrl"
