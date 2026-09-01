param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RuntimeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $RuntimeRoot ".venv"
$PythonExe = Join-Path $Venv "Scripts\python.exe"
$Requirements = Join-Path $RuntimeRoot "requirements.txt"

Write-Host "Dentora Voice validation environment"
Write-Host "Runtime root: $RuntimeRoot"

if (-not (Test-Path $PythonExe)) {
    & $Python -m venv $Venv
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r $Requirements

Write-Host "Installed Voice-only dependencies into: $Venv"
Write-Host "No Whisper model was downloaded by this script."
