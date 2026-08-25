# Dentora transactional updater for the Windows client package.
# Requires Docker Desktop and Windows PowerShell 5.1+. This script deliberately
# never uses :latest: a GitHub Release manifest supplies immutable OCI digests.
[CmdletBinding()]
param(
    [ValidateSet('Check','Update','Recover')]
    [string]$Mode = 'Check',
    [switch]$Force,
    [string]$SimulateFailureAt = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$EnvFile = Join-Path $Root '.env.client'
$Compose = Join-Path $Root 'docker-compose.client.yml'
$UpdateRoot = Join-Path $Root '.dentora-update'
$StateFile = Join-Path $UpdateRoot 'status.json'
$Transactions = Join-Path $UpdateRoot 'transactions'
New-Item -ItemType Directory -Force -Path $Transactions | Out-Null

function Write-Status([string]$State, [string]$Message, $Extra = @{}) {
    $data = [ordered]@{ state=$State; message=$Message; updatedAt=(Get-Date).ToUniversalTime().ToString('o') }
    foreach ($key in $Extra.Keys) { $data[$key] = $Extra[$key] }
    $data | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StateFile -Encoding UTF8
    Write-Host "[$State] $Message"
}
function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed ($LASTEXITCODE): docker $($Arguments -join ' ')" }
}
function Get-EnvMap {
    if (!(Test-Path $EnvFile)) { throw '.env.client is missing. Start Dentora once before checking for updates.' }
    $map = [ordered]@{}
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#\s][^=]*)=(.*)$') { $map[$matches[1].Trim()] = $matches[2] }
    }
    return $map
}
function Set-EnvValues($Values) {
    $lines = @(Get-Content $EnvFile)
    foreach ($key in $Values.Keys) {
        $found = $false
        for ($i=0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "^$([regex]::Escape($key))=") { $lines[$i] = "$key=$($Values[$key])"; $found = $true }
        }
        if (!$found) { $lines += "$key=$($Values[$key])" }
    }
    [IO.File]::WriteAllLines($EnvFile, [string[]]$lines, (New-Object Text.UTF8Encoding($false)))
}
function Convert-Version([string]$Value) {
    if ($Value -notmatch '^v?(\d+)\.(\d+)\.(\d+)$') { throw "Invalid semantic version: $Value" }
    return [version]"$($matches[1]).$($matches[2]).$($matches[3])"
}
function Get-Release($Repository) {
    $headers = @{ 'Accept'='application/vnd.github+json'; 'User-Agent'='Dentora-Updater' }
    try { return Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$Repository/releases/latest" -TimeoutSec 30 }
    catch { throw "Could not obtain the latest published release. No update was applied. $($_.Exception.Message)" }
}
function Download-ReleaseManifest($Release, [string]$Directory) {
    $manifest = @($Release.assets | Where-Object { $_.name -eq 'dentora-release-manifest.json' })[0]
    $checksum = @($Release.assets | Where-Object { $_.name -eq 'dentora-release-manifest.json.sha256' })[0]
    if ($null -eq $manifest -or $null -eq $checksum) { throw 'Release is missing its manifest or checksum asset.' }
    $manifestPath = Join-Path $Directory $manifest.name; $checksumPath = Join-Path $Directory $checksum.name
    Invoke-WebRequest -UseBasicParsing -Headers @{ 'Accept'='application/octet-stream'; 'User-Agent'='Dentora-Updater' } -Uri $manifest.browser_download_url -OutFile $manifestPath
    Invoke-WebRequest -UseBasicParsing -Headers @{ 'Accept'='application/octet-stream'; 'User-Agent'='Dentora-Updater' } -Uri $checksum.browser_download_url -OutFile $checksumPath
    # GitHub's API itself supplies a SHA-256 for release assets. Verify both
    # downloaded files before trusting the release-provided checksum.
    foreach ($asset in @($manifest,$checksum)) {
        if ($asset.PSObject.Properties.Name -contains 'digest' -and $asset.digest -match '^sha256:') {
            $path = Join-Path $Directory $asset.name
            $actual = 'sha256:' + (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
            if ($actual -ne $asset.digest.ToLowerInvariant()) { throw "GitHub asset digest mismatch for $($asset.name)" }
        }
    }
    $expected = ((Get-Content $checksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw 'Release manifest checksum verification failed.' }
    $json = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($json.schema -ne 1 -or !$json.version -or !$json.images.backend -or !$json.images.frontend) { throw 'Release manifest has an unsupported schema.' }
    if ((Convert-Version $json.version) -ne (Convert-Version $Release.tag_name)) { throw 'Release manifest version does not match the GitHub tag.' }
    return $json
}
function Assert-ImmutableImage([string]$Reference) {
    if ($Reference -notmatch '^ghcr\.io/.+@sha256:[a-f0-9]{64}$') { throw "Release image is not an immutable GHCR digest: $Reference" }
    Invoke-Docker @('pull',$Reference)
    # Docker validates content-addressed OCI digests while pulling. Confirm the
    # locally accepted image reports the exact manifest digest from the signed
    # release manifest; no mutable tag is consulted after this point.
    $repoDigests = (& docker image inspect $Reference --format '{{join .RepoDigests "\\n"}}')
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect pulled OCI image for $Reference" }
    $expected = ($Reference -split '@')[1].ToLowerInvariant()
    if (($repoDigests | Where-Object { $_.ToLowerInvariant().EndsWith('@' + $expected) }).Count -eq 0) {
        throw "OCI digest verification failed for $Reference"
    }
}
function Invoke-DockerWithStdin([string[]]$Arguments, [string]$InputFile) {
    # PowerShell's normal pipeline turns binary tar bytes into objects. Feed
    # stdin at the stream level so storage archives are restored byte-for-byte.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'docker'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $psi.Arguments = (($Arguments | ForEach-Object { '"' + ($_ -replace '"','\\"') + '"' }) -join ' ')
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $source = [IO.File]::OpenRead($InputFile)
    try { $source.CopyTo($process.StandardInput.BaseStream); $process.StandardInput.Close() } finally { $source.Dispose() }
    $stdout = $process.StandardOutput.ReadToEnd(); $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Docker stdin command failed ($($process.ExitCode)): $stderr $stdout" }
}
function Wait-Healthy {
    for ($i=0; $i -lt 60; $i++) {
        try {
            & docker compose --env-file $EnvFile -f $Compose exec -T backend python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/ready',timeout=3).status==200 else 1)" 2>$null
            $back = $LASTEXITCODE
            & docker compose --env-file $EnvFile -f $Compose exec -T frontend wget -q -O /dev/null http://127.0.0.1:3000/ 2>$null
            if ($back -eq 0 -and $LASTEXITCODE -eq 0) { return }
        } catch {}
        Start-Sleep -Seconds 3
    }
    throw 'Backend readiness or frontend health did not succeed within 180 seconds.'
}
function New-Backup([string]$Directory, $Config) {
    $dbFile = Join-Path $Directory 'database.sql'; $storageFile = Join-Path $Directory 'storage.tar.gz'
    # --clean makes recovery independent of changed/new tables after a failed migration.
    & docker compose --env-file $EnvFile -f $Compose exec -T db pg_dump --clean --if-exists -U $Config.POSTGRES_USER -d $Config.POSTGRES_DB > $dbFile
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $dbFile) -or (Get-Item $dbFile).Length -lt 32) { throw 'Database backup failed; update was not started.' }
    & docker compose --env-file $EnvFile -f $Compose exec -T backend tar -C /app/storage -czf - . > $storageFile
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $storageFile) -or (Get-Item $storageFile).Length -lt 20) { throw 'Storage backup failed; update was not started.' }
    return @{ database=$dbFile; storage=$storageFile }
}
function Restore-Backup([string]$Directory, $Config) {
    $dbFile = Join-Path $Directory 'database.sql'; $storageFile = Join-Path $Directory 'storage.tar.gz'
    if (!(Test-Path $dbFile) -or !(Test-Path $storageFile)) { throw 'Recovery backup is incomplete.' }
    Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'stop','backend','frontend','caddy')
    & docker compose --env-file $EnvFile -f $Compose exec -T db psql -v ON_ERROR_STOP=1 -U $Config.POSTGRES_USER -d $Config.POSTGRES_DB < $dbFile
    if ($LASTEXITCODE -ne 0) { throw 'Database restore failed.' }
    # Preserve the mounted volume and replace only its contents.
    Invoke-DockerWithStdin @('compose','--env-file',$EnvFile,'-f',$Compose,'run','--rm','--no-deps','-T','backend','sh','-c','rm -rf /app/storage/* /app/storage/.[!.]* /app/storage/..?*; tar -C /app/storage -xzf -') $storageFile
}

if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop CLI was not found.' }
$cfg = Get-EnvMap
$repository = if ($cfg.DENTORA_RELEASE_REPOSITORY) { $cfg.DENTORA_RELEASE_REPOSITORY } else { 'abdelnabym519-cpu/dentora-clinic' }
$current = if ($cfg.DENTORA_VERSION) { $cfg.DENTORA_VERSION } else { throw 'DENTORA_VERSION is missing from .env.client.' }
$release = Get-Release $repository
$latest = ($release.tag_name -replace '^v','')
$transaction = Join-Path $Transactions ((Get-Date).ToString('yyyyMMdd-HHmmss') + '-' + $latest)
New-Item -ItemType Directory -Force -Path $transaction | Out-Null
$manifest = Download-ReleaseManifest $release $transaction

if ($Mode -eq 'Check') {
    $available = (Convert-Version $latest) -gt (Convert-Version $current)
    Write-Status ($(if($available){'update-available'}else{'up-to-date'})) "Installed $current; latest published $latest." @{installedVersion=$current; latestVersion=$latest; updateAvailable=$available; releaseUrl=$release.html_url}
    exit 0
}
if ($Mode -eq 'Recover') {
    $last = Get-ChildItem $Transactions -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $last -or !(Test-Path (Join-Path $last.FullName 'env.before'))) { throw 'No recoverable update transaction was found.' }
    Copy-Item (Join-Path $last.FullName 'env.before') $EnvFile -Force
    $old = Get-EnvMap; Restore-Backup $last.FullName $old; Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'up','-d'); Wait-Healthy
    Write-Status 'recovered' "Recovered from transaction $($last.Name)." @{installedVersion=$old.DENTORA_VERSION}; exit 0
}
if ((Convert-Version $latest) -le (Convert-Version $current) -and !$Force) { Write-Status 'up-to-date' "Installed $current is not older than $latest." @{installedVersion=$current}; exit 0 }

try {
    Write-Status 'verifying' "Verifying immutable release $latest." @{installedVersion=$current; targetVersion=$latest}
    if ((Get-PSDrive -Name ((Split-Path $Root -Qualifier).TrimEnd(':'))).Free -lt 4GB) { throw 'Less than 4 GB free disk space; update was not started.' }
    Assert-ImmutableImage $manifest.images.backend; Assert-ImmutableImage $manifest.images.frontend
    Copy-Item $EnvFile (Join-Path $transaction 'env.before') -Force
    $backup = New-Backup $transaction $cfg
    if ($SimulateFailureAt -eq 'after-backup') { throw 'Simulated failure after backup.' }
    Set-EnvValues @{ DENTORA_VERSION=$latest; DENTORA_BACKEND_IMAGE=$manifest.images.backend; DENTORA_FRONTEND_IMAGE=$manifest.images.frontend }
    Write-Status 'installing' "Installing $latest after verified backup." @{transaction=$transaction}
    Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'up','-d')
    if ($SimulateFailureAt -eq 'after-install') { throw 'Simulated failure after install.' }
    Wait-Healthy
    if ($SimulateFailureAt -eq 'after-health') { throw 'Simulated failure after health.' }
    Write-Status 'updated' "Dentora was updated successfully to $latest." @{installedVersion=$latest; transaction=$transaction; backup=$backup}
} catch {
    $reason = $_.Exception.Message
    Set-Content -LiteralPath (Join-Path $transaction 'failure.txt') -Value $reason -Encoding UTF8
    try {
        if (Test-Path (Join-Path $transaction 'env.before')) {
            Copy-Item (Join-Path $transaction 'env.before') $EnvFile -Force
            $old = Get-EnvMap
            if (Test-Path (Join-Path $transaction 'database.sql')) { Restore-Backup $transaction $old }
            Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'up','-d')
            Wait-Healthy
            Write-Status 'rolled-back' "Update failed and the previous release was restored: $reason" @{installedVersion=$old.DENTORA_VERSION; transaction=$transaction}
            exit 1
        }
    } catch { $reason += " Recovery also failed: $($_.Exception.Message)" }
    Write-Status 'failed' $reason @{installedVersion=$current; transaction=$transaction}
    throw
}
