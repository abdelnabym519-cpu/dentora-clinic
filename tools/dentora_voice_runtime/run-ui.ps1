param(
    [string]$BackendUrl = "http://127.0.0.1:8100",
    [int]$Port = 3000
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Frontend = Join-Path $RepoRoot "frontend"
$ModulesDir = Join-Path $RepoRoot "backend\app\modules"
$ModulesJson = Join-Path $Frontend "modules.json"
$HadModulesJson = Test-Path $ModulesJson
$SavedModulesJson = $null

if ($HadModulesJson) {
    $SavedModulesJson = Get-Content -Raw -Encoding UTF8 $ModulesJson
}

try {
    $entries = @()
    Get-ChildItem $ModulesDir -Directory | Sort-Object Name | ForEach-Object {
        $layer = Join-Path $_.FullName "frontend"
        if (Test-Path $layer) {
            $entries += [PSCustomObject]@{
                name = $_.Name
                path = [System.IO.Path]::GetFullPath($layer)
            }
        }
    }
    @{
        layers = @($entries | ForEach-Object { $_.path })
        modules = $entries
        version = 1
    } | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $ModulesJson

    $env:NUXT_PUBLIC_API_BASE_URL = $BackendUrl
    $env:API_BASE_URL_SERVER = $BackendUrl
    $env:NITRO_HOST = "127.0.0.1"
    $env:NITRO_PORT = "$Port"

    Write-Host "Starting Dentora UI for local Voice validation"
    Write-Host "UI: http://localhost:$Port"
    Write-Host "Backend: $BackendUrl"
    Write-Host "Module layers: host-local paths generated temporarily"

    Push-Location $Frontend
    try {
        npm run dev
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($HadModulesJson) {
        $SavedModulesJson | Set-Content -Encoding UTF8 $ModulesJson
    }
    elseif (Test-Path $ModulesJson) {
        Remove-Item $ModulesJson -Force
    }
}
