$ErrorActionPreference = "Stop"

$Server = Join-Path $PSScriptRoot "server.py"
$Requirements = Join-Path $PSScriptRoot "requirements.txt"

$ServerText = Get-Content -Raw -Encoding UTF8 $Server
$RequirementsText = Get-Content -Raw -Encoding UTF8 $Requirements

$RequiredPatterns = @(
    'HOST = "127.0.0.1"',
    'local_files_only=True',
    'DEVICE = os.getenv("DENTORA_VOICE_DEVICE", "cpu")',
    'COMPUTE_TYPE = os.getenv("DENTORA_VOICE_COMPUTE_TYPE", "int8")'
)

foreach ($Pattern in $RequiredPatterns) {
    if (-not $ServerText.Contains($Pattern)) {
        throw "Offline verification failed: required runtime setting not found: $Pattern"
    }
}

$Forbidden = @(
    "openai",
    "azure-cognitiveservices-speech",
    "google-cloud-speech",
    "boto3",
    "assemblyai",
    "deepgram",
    "elevenlabs"
)

$ScanText = ($ServerText + "`n" + $RequirementsText).ToLowerInvariant()
foreach ($Token in $Forbidden) {
    if ($ScanText.Contains($Token)) {
        throw "Offline verification failed: forbidden cloud speech dependency/reference found: $Token"
    }
}

Write-Host "PASS: runtime binds to 127.0.0.1"
Write-Host "PASS: model loading uses local_files_only=True"
Write-Host "PASS: default device is CPU"
Write-Host "PASS: default compute type is INT8"
Write-Host "PASS: no known cloud speech SDK dependency/reference found in runtime code or requirements"
Write-Host "NOTE: run verify-network.ps1 during a real STT request for runtime network evidence."
