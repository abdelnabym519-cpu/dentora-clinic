param([ValidateSet("check", "apply", "recover")][string]$Action = "check")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = Join-Path $Root ".env.client"
$Compose = Join-Path $Root "docker-compose.client.yml"
$Journal = Join-Path $Root ".dentora-update-journal.json"
$Runtime = Join-Path $env:TEMP "DentoraAutoUpdate"
Set-Location $Root

function Get-Env([string]$Name) {
    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
        if ($line.StartsWith("$Name=", [StringComparison]::Ordinal)) { return $line.Substring($Name.Length + 1) }
    }
    return ""
}
function Get-Version([string]$Base = $Root) {
    $text = [IO.File]::ReadAllText((Join-Path $Base "backend\pyproject.toml"))
    $m = [Regex]::Match($text, '(?m)^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$')
    if (-not $m.Success) { throw "Could not determine Dentora version." }
    return $m.Groups[1].Value
}
function Assert-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Administrator privileges are required." }
}
function Invoke-Compose([string[]]$Args) {
    & docker compose --env-file $EnvFile -f $Compose @Args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE." }
}
function Wait-Health {
    $url = Get-Env "PUBLIC_URL"; if ([string]::IsNullOrWhiteSpace($url)) { $url = "http://localhost" }
    $health = $url.TrimEnd('/') + "/health"
    for ($i = 0; $i -lt 45; $i++) {
        try { if ((Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 4).StatusCode -eq 200) { return } } catch { }
        Start-Sleep -Seconds 2
    }
    throw "Dentora did not become healthy."
}
function Write-Journal([hashtable]$Value) {
    $tmp = "$Journal.$PID.tmp"
    [IO.File]::WriteAllText($tmp, (($Value | ConvertTo-Json) + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
    Move-Item $tmp $Journal -Force
}
function New-Mutex {
    $m = New-Object Threading.Mutex($false, "DentoraAutoUpdate")
    try { $ok = $m.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ok = $true }
    if (-not $ok) { $m.Dispose(); throw "Another Dentora Auto Update operation is already running." }
    return $m
}
function Validate-Package([string]$Metadata, [string]$Package) {
    $key = Get-Env "UPDATE_PUBLIC_KEY_B64"
    $current = Get-Version
    $mount = "$(Split-Path $Metadata -Parent):/update:ro"
    $out = & docker compose --env-file $EnvFile -f $Compose run --rm --no-deps -v $mount --entrypoint python backend -m app.cli.update_artifact --metadata /update/update.json --package /update/dentora-update.zip --public-key-b64 $key --current-version $current
    if ($LASTEXITCODE -ne 0) { throw "Signed update validation failed." }
    return ($out | Out-String | ConvertFrom-Json)
}
function Download-Update {
    $metadataUrl = Get-Env "UPDATE_METADATA_URL"
    if ($metadataUrl -notmatch '^https://') { throw "UPDATE_METADATA_URL must use HTTPS." }
    if ([string]::IsNullOrWhiteSpace((Get-Env "UPDATE_PUBLIC_KEY_B64"))) { throw "UPDATE_PUBLIC_KEY_B64 is required." }
    $dir = Join-Path $Runtime ([Guid]::NewGuid().ToString("N")); New-Item -ItemType Directory $dir -Force | Out-Null
    $metadata = Join-Path $dir "update.json"; Invoke-WebRequest -UseBasicParsing -Uri $metadataUrl -OutFile $metadata -TimeoutSec 60
    $raw = Get-Content $metadata -Raw | ConvertFrom-Json
    $packageUrl = [string]$raw.descriptor.package_url
    if ($packageUrl -notmatch '^https://') { throw "Update package URL must use HTTPS." }
    $package = Join-Path $dir "dentora-update.zip"; Invoke-WebRequest -UseBasicParsing -Uri $packageUrl -OutFile $package -TimeoutSec 120
    $descriptor = Validate-Package $metadata $package
    return @{ Dir=$dir; Package=$package; Descriptor=$descriptor }
}
function New-Backup {
    $script = Join-Path $Root "scripts\dentora_backup_restore.ps1"
    $output = & $script -Action backup 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Mandatory pre-update backup failed." }
    $line = @($output | Where-Object { [string]$_ -match '^Artifact:\s+(.+\.zip)$' }) | Select-Object -Last 1
    if ($null -eq $line) { throw "Backup artifact path was not returned." }
    return [Regex]::Match([string]$line, '^Artifact:\s+(.+\.zip)$').Groups[1].Value
}
function Recover {
    if (-not (Test-Path $Journal)) { Write-Host "No interrupted update was found."; return }
    $j = Get-Content $Journal -Raw | ConvertFrom-Json
    if (-not (Test-Path ([string]$j.snapshot))) { throw "Rollback snapshot is missing. Dentora remains fail-closed." }
    Copy-Item (Join-Path ([string]$j.snapshot) '*') $Root -Recurse -Force
    Invoke-Compose @("up", "-d", "--build", "db", "backend", "frontend", "caddy")
    if (Test-Path ([string]$j.backup)) { & (Join-Path $Root "scripts\dentora_backup_restore.ps1") -Action restore -ArtifactPath ([string]$j.backup) }
    Wait-Health
    Remove-Item $Journal -Force
}
function Apply {
    if (Test-Path $Journal) { throw "Recover the interrupted update first." }
    $u = Download-Update; $stage = Join-Path $u.Dir "stage"; $snapshot = Join-Path $u.Dir "snapshot"
    Expand-Archive -LiteralPath $u.Package -DestinationPath $stage
    if ((Get-Version $stage) -ne [string]$u.Descriptor.version) { throw "Staged version does not match signed metadata." }
    foreach ($protected in @(".env.client", "backups", ".dentora-update-journal.json", ".dentora-restore-journal.json", ".git")) {
        if (Test-Path (Join-Path $stage $protected)) { throw "Update package contains protected installation state." }
    }
    New-Item -ItemType Directory $snapshot -Force | Out-Null
    foreach ($item in Get-ChildItem $Root -Force) {
        if ($item.Name -notin @(".env.client", "backups", ".dentora-update-journal.json", ".dentora-restore-journal.json", ".git")) { Copy-Item $item.FullName $snapshot -Recurse -Force }
    }
    $backup = New-Backup
    $state = @{ version=1; phase="prepared"; target=[string]$u.Descriptor.version; snapshot=$snapshot; backup=$backup }; Write-Journal $state
    try {
        Copy-Item (Join-Path $stage '*') $Root -Recurse -Force
        $state.phase="files_applied"; Write-Journal $state
        Invoke-Compose @("up", "-d", "--build", "db", "backend", "frontend", "caddy")
        $state.phase="services_started"; Write-Journal $state
        Wait-Health
        if ((Get-Version) -ne [string]$u.Descriptor.version) { throw "Installed version mismatch." }
        Remove-Item $Journal -Force
        Write-Host "Dentora update succeeded: $($u.Descriptor.version)"
    } catch { $original=$_; try { Recover } catch { throw "Update and rollback both failed. Dentora remains fail-closed." }; throw $original }
}

Assert-Admin
if (-not (Test-Path $EnvFile)) { throw ".env.client is missing." }
& docker info *> $null; if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running." }
$mutex = New-Mutex
try {
    switch ($Action) {
        "check" { $u=Download-Update; Write-Host "Update available: $($u.Descriptor.version)"; Remove-Item $u.Dir -Recurse -Force }
        "apply" { Apply }
        "recover" { Recover }
    }
} finally { try { $mutex.ReleaseMutex() } catch { }; $mutex.Dispose() }
