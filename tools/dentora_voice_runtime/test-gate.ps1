param(
    [Parameter(Mandatory = $true)]
    [string]$PostgresPassword,
    [string]$PostgresUser = "dental",
    [string]$BackendPython = "python",
    [string]$E2EBaseUrl = "http://localhost:3100"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Frontend = Join-Path $RepoRoot "frontend"
$ModulesDir = Join-Path $RepoRoot "backend\app\modules"
$ModuleJunction = Join-Path $Frontend "module_layers"
$ModulesJson = Join-Path $Frontend "modules.json"
$CreatedJunction = $false
$SavedModulesJson = $null
$HadModulesJson = Test-Path $ModulesJson
$VoiceBaseSha = "e35500a00998879af9bfe7e0cab6792e7b9d268e"

function Invoke-Checked([string]$Label, [scriptblock]$Command) {
    Write-Host ""
    Write-Host "=== $Label ==="
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
    Write-Host "PASS: $Label"
}

function Wait-Http([string]$Url, [string]$Label, [int]$Attempts = 90) {
    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                Write-Host "PASS: $Label reachable at $Url"
                return
            }
        }
        catch {
        }
        Start-Sleep -Seconds 2
    }
    throw "$Label did not become reachable at $Url"
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $Encoding)
}

Set-Location $RepoRoot
$branch = (& git branch --show-current).Trim()
$head = (& git rev-parse HEAD).Trim()
$mergeBase = (& git merge-base HEAD $VoiceBaseSha).Trim()
if ($mergeBase -ne $VoiceBaseSha) {
    throw "Wrong validation lineage: merge-base is $mergeBase, expected $VoiceBaseSha."
}
if ($branch -and $branch -ne "feat/dentora-voice") {
    throw "Wrong branch: $branch. Use feat/dentora-voice or an isolated detached worktree from it."
}
if ($branch) {
    Write-Host "Validation branch: $branch @ $head"
}
else {
    Write-Host "Validation detached worktree: $head"
}

if (Test-Path $BackendPython -PathType Leaf) {
    $BackendPython = (Resolve-Path $BackendPython).Path
}

$env:POSTGRES_PASSWORD = $PostgresPassword
$env:POSTGRES_USER = $PostgresUser
$env:SECRET_KEY = "dentora-voice-local-validation-secret-key-only"
$env:ENVIRONMENT = "development"
$env:API_BASE_URL = "http://localhost:8100"

try {
    if ($HadModulesJson) {
        $SavedModulesJson = Get-Content -Raw -Encoding UTF8 $ModulesJson
    }

    if (-not (Test-Path $ModuleJunction)) {
        New-Item -ItemType Junction -Path $ModuleJunction -Target $ModulesDir | Out-Null
        $CreatedJunction = $true
    }

    $moduleEntries = @()
    Get-ChildItem $ModulesDir -Directory | Sort-Object Name | ForEach-Object {
        $layer = Join-Path $_.FullName "frontend"
        if (Test-Path $layer) {
            $moduleEntries += [PSCustomObject]@{
                name = $_.Name
                path = [System.IO.Path]::GetFullPath($layer)
            }
        }
    }
    $ModulesConfig = @{
        layers = @($moduleEntries | ForEach-Object { $_.path })
        modules = $moduleEntries
        version = 1
    } | ConvertTo-Json -Depth 5
    Write-Utf8NoBom $ModulesJson $ModulesConfig

    Write-Host "Starting isolated local Dentora services required by backend/E2E validation..."
    Invoke-Checked "Docker db/backend/frontend startup" { docker compose up -d db backend frontend }
    Wait-Http "http://127.0.0.1:8100/health" "Backend"
    Wait-Http "$E2EBaseUrl/login" "Frontend"

    Invoke-Checked "Create clean backend test database" {
        docker compose exec -T db psql -U $PostgresUser -d postgres -c "DROP DATABASE IF EXISTS dental_clinic_test WITH (FORCE);"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        docker compose exec -T db psql -U $PostgresUser -d postgres -c "CREATE DATABASE dental_clinic_test;"
    }

    $env:DATABASE_URL = "postgresql+asyncpg://${PostgresUser}:${PostgresPassword}@127.0.0.1:55434/dental_clinic_test"
    $env:TESTING = "true"

    Push-Location (Join-Path $RepoRoot "backend")
    try {
        Invoke-Checked "Voice unit tests" {
            & $BackendPython -m pytest tests/modules/voice/test_intent.py -v --tb=short
        }
        Invoke-Checked "Voice integration tests" {
            & $BackendPython -m pytest tests/modules/voice/test_voice_api.py -v --tb=short
        }
        Invoke-Checked "Voice security/privacy tests" {
            & $BackendPython -m pytest `
                tests/modules/voice/test_voice_privacy.py `
                tests/modules/voice/test_voice_api.py::test_ambiguous_patient_stops_before_navigation `
                tests/modules/voice/test_voice_api.py::test_cross_tenant_patient_cannot_be_resolved `
                tests/modules/voice/test_voice_api.py::test_domain_permission_is_rechecked_at_tool_registry `
                tests/modules/voice/test_voice_api.py::test_multi_step_stops_after_missing_cbct `
                tests/modules/voice/test_voice_api.py::test_unsupported_repository_target_fails_closed `
                -v --tb=short
        }
        Invoke-Checked "Full backend tests" {
            & $BackendPython -m pytest -v --tb=short
        }
        Invoke-Checked "Alembic round-trip" {
            & $BackendPython -m pytest -v -m alembic_roundtrip --tb=short
        }
    }
    finally {
        Pop-Location
    }

    Invoke-Checked "Ruff check" { & $BackendPython -m ruff check backend/ }
    Invoke-Checked "Ruff format check" { & $BackendPython -m ruff format --check backend/ }

    Push-Location $Frontend
    try {
        Invoke-Checked "Frontend tests" { npm run test -- --run }
        Invoke-Checked "ESLint" { npm run lint }
        Invoke-Checked "Typecheck" { npm run typecheck }
        Invoke-Checked "Production build" { npm run build }

        $env:E2E_BASE_URL = $E2EBaseUrl
        Invoke-Checked "Seed E2E demo data" {
            docker compose exec -T backend bash -c "PYTHONPATH=/app python /app/scripts/seed_demo.py --lang es"
        }
        Invoke-Checked "Playwright E2E" { npx playwright test }
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "ALL LOCAL TEST GATES PASSED."
}
finally {
    if ($HadModulesJson) {
        Write-Utf8NoBom $ModulesJson $SavedModulesJson
    }
    elseif (Test-Path $ModulesJson) {
        Remove-Item $ModulesJson -Force
    }

    if ($CreatedJunction -and (Test-Path $ModuleJunction)) {
        Remove-Item $ModuleJunction -Force
    }
}
