param(
    [string]$ModelPath = "models/faster-whisper-small",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Server = Join-Path $PSScriptRoot "server.py"

if (-not (Test-Path $PythonExe)) {
    throw "Voice venv not found. Run: powershell -ExecutionPolicy Bypass -File tools/dentora_voice_runtime/install.ps1"
}

if (-not [System.IO.Path]::IsPathRooted($ModelPath)) {
    $ModelPath = Join-Path $RepoRoot $ModelPath
}
$ModelPath = [System.IO.Path]::GetFullPath($ModelPath)

if (-not (Test-Path (Join-Path $ModelPath "model.bin"))) {
    throw "Local CTranslate2 faster-whisper model not found: $ModelPath"
}

$env:DENTORA_VOICE_MODEL_PATH = $ModelPath
$env:DENTORA_VOICE_DEVICE = "cpu"
$env:DENTORA_VOICE_COMPUTE_TYPE = "int8"
$env:DENTORA_VOICE_PORT = "$Port"

Write-Host "Starting Dentora Voice local runtime"
Write-Host "Model: $ModelPath"
Write-Host "Device: CPU"
Write-Host "Compute: INT8"
Write-Host "Bind: http://127.0.0.1:$Port"
Write-Host "Automatic model download: disabled"

& $PythonExe $Server
