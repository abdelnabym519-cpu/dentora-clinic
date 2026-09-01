param(
    [string]$BaseModel = "models/faster-whisper-base",
    [string]$SmallModel = "models/faster-whisper-small",
    [Parameter(Mandatory = $true)]
    [string[]]$Sample,
    [string]$Output = "dentora-voice-benchmark.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Benchmark = Join-Path $PSScriptRoot "benchmark.py"

if (-not (Test-Path $PythonExe)) {
    throw "Voice venv not found. Run install.ps1 first."
}

function Resolve-RepoPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $PathValue))
}

$BaseModel = Resolve-RepoPath $BaseModel
$SmallModel = Resolve-RepoPath $SmallModel
$Output = Resolve-RepoPath $Output

foreach ($Model in @($BaseModel, $SmallModel)) {
    if (-not (Test-Path (Join-Path $Model "model.bin"))) {
        throw "Local CTranslate2 model missing model.bin: $Model"
    }
}

$Args = @(
    $Benchmark,
    "--base-model", $BaseModel,
    "--small-model", $SmallModel,
    "--output", $Output
)

foreach ($Item in $Sample) {
    $Resolved = Resolve-RepoPath $Item
    if (-not (Test-Path $Resolved)) {
        throw "Audio sample not found: $Resolved"
    }
    $Args += @("--sample", $Resolved)
}

Write-Host "Running local Dentora Voice hardware benchmark"
Write-Host "Models: base multilingual + small multilingual"
Write-Host "Device: CPU / INT8"
Write-Host "Privacy: transcript, audio bytes, PHI and source filenames are not written to the report"
Write-Host "Output: $Output"

& $PythonExe @Args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
