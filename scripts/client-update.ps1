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
$OfficialRepository = 'abdelnabym519-cpu/dentora-clinic'
New-Item -ItemType Directory -Force -Path $Transactions | Out-Null

function Write-Status([string]$State, [string]$Message, $Extra = @{}) {
    $data = [ordered]@{ state=$State; message=$Message; updatedAt=(Get-Date).ToUniversalTime().ToString('o') }
    foreach ($key in $Extra.Keys) { $data[$key] = $Extra[$key] }
    $data | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StateFile -Encoding UTF8
    Write-Host "[$State] $Message"
}
function Quote-NativeArgument([string]$Value) {
    return '"' + ($Value -replace '"','\\"') + '"'
}
function New-DockerProcess([string[]]$Arguments, [bool]$RedirectInput, [bool]$RedirectOutput) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'docker'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $RedirectInput
    $psi.RedirectStandardOutput = $RedirectOutput
    $psi.RedirectStandardError = $true
    $psi.Arguments = (($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    return $process
}
function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed ($LASTEXITCODE): docker $($Arguments -join ' ')" }
}
function Invoke-DockerToFile([string[]]$Arguments, [string]$OutputFile) {
    $process = New-DockerProcess $Arguments $false $true
    $target = [IO.File]::Open($OutputFile, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $process.StandardOutput.BaseStream.CopyTo($target) } finally { $target.Dispose() }
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Docker output command failed ($($process.ExitCode)): $stderr" }
}
function Invoke-DockerWithStdin([string[]]$Arguments, [string]$InputFile) {
    $process = New-DockerProcess $Arguments $true $true
    $source = [IO.File]::OpenRead($InputFile)
    try { $source.CopyTo($process.StandardInput.BaseStream); $process.StandardInput.Close() } finally { $source.Dispose() }
    $stdout = $process.StandardOutput.ReadToEnd(); $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Docker stdin command failed ($($process.ExitCode)): $stderr $stdout" }
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
function Assert-ReleaseDescriptor($Release) {
    if ($null -eq $Release) { throw 'Invalid GitHub Release descriptor.' }
    if ([string]$Release.tag_name -notmatch '^v\d+\.\d+\.\d+$') { throw 'GitHub Release has an invalid version tag.' }
    if ($Release.draft -eq $true -or $Release.prerelease -eq $true) { throw 'GitHub Release is not a final published release.' }
    if ($null -eq $Release.assets) { throw 'GitHub Release assets are missing.' }
}
function Assert-ManifestChecksum([string]$ManifestPath, [string]$ChecksumPath) {
    $expected = ((Get-Content $ChecksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$') { throw 'Release manifest checksum file is invalid.' }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $ManifestPath).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw 'Release manifest checksum verification failed.' }
}
function Assert-ImmutableImageReference([string]$Reference, [string]$Repository, [string]$ImageName) {
    $prefix = [regex]::Escape("ghcr.io/$Repository-$ImageName@sha256:")
    if ($Reference -notmatch "^${prefix}[a-f0-9]{64}$") {
        throw "Release image is not an authorized immutable GHCR digest: $Reference"
    }
}
function Assert-ReleaseManifest($Json, $Release, [string]$Repository) {
    Assert-ReleaseDescriptor $Release
    if ($Json.schema -ne 1 -or !$Json.version -or !$Json.tag -or !$Json.images.backend -or !$Json.images.frontend) {
        throw 'Release manifest has an unsupported schema.'
    }
    if ([string]$Json.tag -ne [string]$Release.tag_name) { throw 'Release manifest tag does not match the GitHub Release.' }
    if ((Convert-Version ([string]$Json.version)) -ne (Convert-Version ([string]$Release.tag_name))) {
        throw 'Release manifest version does not match the GitHub tag.'
    }
    Assert-ImmutableImageReference ([string]$Json.images.backend) $Repository 'backend'
    Assert-ImmutableImageReference ([string]$Json.images.frontend) $Repository 'frontend'
}
function Get-Release([string]$Repository) {
    if ($Repository -ne $OfficialRepository) { throw "Unauthorized release repository: $Repository" }
    $headers = @{ 'Accept'='application/vnd.github+json'; 'User-Agent'='Dentora-Updater' }
    try { $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$Repository/releases/latest" -TimeoutSec 30 }
    catch { throw "Could not obtain the latest published release. No update was applied. $($_.Exception.Message)" }
    Assert-ReleaseDescriptor $release
    return $release
}
function Download-ReleaseManifest($Release, [string]$Directory, [string]$Repository) {
    Assert-ReleaseDescriptor $Release
    $manifest = @($Release.assets | Where-Object { $_.name -eq 'dentora-release-manifest.json' })[0]
    $checksum = @($Release.assets | Where-Object { $_.name -eq 'dentora-release-manifest.json.sha256' })[0]
    if ($null -eq $manifest -or $null -eq $checksum) { throw 'Release is missing its manifest or checksum asset.' }
    $manifestPath = Join-Path $Directory $manifest.name; $checksumPath = Join-Path $Directory $checksum.name
    Invoke-WebRequest -UseBasicParsing -Headers @{ 'Accept'='application/octet-stream'; 'User-Agent'='Dentora-Updater' } -Uri $manifest.browser_download_url -OutFile $manifestPath
    Invoke-WebRequest -UseBasicParsing -Headers @{ 'Accept'='application/octet-stream'; 'User-Agent'='Dentora-Updater' } -Uri $checksum.browser_download_url -OutFile $checksumPath
    # GitHub's API supplies SHA-256 digests for release assets when available.
    foreach ($asset in @($manifest,$checksum)) {
        if ($asset.PSObject.Properties.Name -contains 'digest' -and $asset.digest -match '^sha256:') {
            $path = Join-Path $Directory $asset.name
            $actual = 'sha256:' + (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
            if ($actual -ne $asset.digest.ToLowerInvariant()) { throw "GitHub asset digest mismatch for $($asset.name)" }
        }
    }
    Assert-ManifestChecksum $manifestPath $checksumPath
    $json = Get-Content $manifestPath -Raw | ConvertFrom-Json
    Assert-ReleaseManifest $json $Release $Repository
    return $json
}
function Assert-ImmutableImage([string]$Reference, [string]$Repository, [string]$ImageName) {
    Assert-ImmutableImageReference $Reference $Repository $ImageName
    Invoke-Docker @('pull',$Reference)
    # Docker validates content-addressed OCI digests while pulling. Confirm the
    # locally accepted image reports the exact manifest digest from the release.
    $repoDigests = (& docker image inspect $Reference --format '{{join .RepoDigests "\n"}}')
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect pulled OCI image for $Reference" }
    $expected = ($Reference -split '@')[1].ToLowerInvariant()
    if (($repoDigests | Where-Object { $_.ToLowerInvariant().EndsWith('@' + $expected) }).Count -eq 0) {
        throw "OCI digest verification failed for $Reference"
    }
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
function Get-FreeDiskBytes {
    $resolved = [IO.Path]::GetFullPath($Root)
    $drive = Get-PSDrive -PSProvider FileSystem | Where-Object {
        $resolved.StartsWith([string]$_.Root, [StringComparison]::OrdinalIgnoreCase)
    } | Sort-Object { ([string]$_.Root).Length } -Descending | Select-Object -First 1
    if ($null -eq $drive) { throw 'Could not determine free disk space for the Dentora installation.' }
    return [int64]$drive.Free
}
function New-Backup([string]$Directory, $Config) {
    $dbFile = Join-Path $Directory 'database.sql'; $storageFile = Join-Path $Directory 'storage.tar.gz'
    # Native process streams are copied byte-for-byte. Windows PowerShell 5.1
    # text redirection would corrupt binary tar output and can re-encode SQL.
    Invoke-DockerToFile @('compose','--env-file',$EnvFile,'-f',$Compose,'exec','-T','db','pg_dump','--clean','--if-exists','-U',$Config.POSTGRES_USER,'-d',$Config.POSTGRES_DB) $dbFile
    if (!(Test-Path $dbFile) -or (Get-Item $dbFile).Length -lt 32) { throw 'Database backup failed; update was not started.' }
    Invoke-DockerToFile @('compose','--env-file',$EnvFile,'-f',$Compose,'exec','-T','backend','tar','-C','/app/storage','-czf','-','.') $storageFile
    if (!(Test-Path $storageFile) -or (Get-Item $storageFile).Length -lt 20) { throw 'Storage backup failed; update was not started.' }
    return @{ database=$dbFile; storage=$storageFile }
}
function Restore-Backup([string]$Directory, $Config) {
    $dbFile = Join-Path $Directory 'database.sql'; $storageFile = Join-Path $Directory 'storage.tar.gz'
    if (!(Test-Path $dbFile) -or !(Test-Path $storageFile)) { throw 'Recovery backup is incomplete.' }
    Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'stop','backend','frontend','caddy')
    Invoke-DockerWithStdin @('compose','--env-file',$EnvFile,'-f',$Compose,'exec','-T','db','psql','-v','ON_ERROR_STOP=1','-U',$Config.POSTGRES_USER,'-d',$Config.POSTGRES_DB) $dbFile
    # Preserve the mounted volume and replace only its contents.
    Invoke-DockerWithStdin @('compose','--env-file',$EnvFile,'-f',$Compose,'run','--rm','--no-deps','-T','backend','sh','-c','rm -rf /app/storage/* /app/storage/.[!.]* /app/storage/..?*; tar -C /app/storage -xzf -') $storageFile
}
function Get-RecoverableTransaction {
    return Get-ChildItem $Transactions -Directory | Where-Object {
        (Test-Path (Join-Path $_.FullName 'env.before')) -and
        (Test-Path (Join-Path $_.FullName 'database.sql')) -and
        (Test-Path (Join-Path $_.FullName 'storage.tar.gz'))
    } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop CLI was not found.' }
$cfg = Get-EnvMap
$repository = if ($cfg.DENTORA_RELEASE_REPOSITORY) { $cfg.DENTORA_RELEASE_REPOSITORY } else { $OfficialRepository }
if ($repository -ne $OfficialRepository) { throw "Unauthorized release repository: $repository" }
$current = if ($cfg.DENTORA_VERSION) { $cfg.DENTORA_VERSION } else { throw 'DENTORA_VERSION is missing from .env.client.' }
[void](Convert-Version $current)

# Recovery must be local-only: a broken/interrupted client may have no network.
if ($Mode -eq 'Recover') {
    $last = Get-RecoverableTransaction
    if ($null -eq $last) { throw 'No recoverable update transaction was found.' }
    Copy-Item (Join-Path $last.FullName 'env.before') $EnvFile -Force
    $old = Get-EnvMap
    Restore-Backup $last.FullName $old
    Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'up','-d')
    Wait-Healthy
    Write-Status 'recovered' "Recovered from transaction $($last.Name)." @{installedVersion=$old.DENTORA_VERSION; transaction=$last.FullName}
    exit 0
}

$release = Get-Release $repository
$latest = ($release.tag_name -replace '^v','')
$transaction = Join-Path $Transactions ((Get-Date).ToString('yyyyMMdd-HHmmss') + '-' + $latest)
New-Item -ItemType Directory -Force -Path $transaction | Out-Null
$manifest = Download-ReleaseManifest $release $transaction $repository

if ($Mode -eq 'Check') {
    $available = (Convert-Version $latest) -gt (Convert-Version $current)
    Write-Status ($(if($available){'update-available'}else{'up-to-date'})) "Installed $current; latest published $latest." @{installedVersion=$current; latestVersion=$latest; updateAvailable=$available; releaseUrl=$release.html_url}
    exit 0
}
if ((Convert-Version $latest) -le (Convert-Version $current) -and !$Force) {
    Write-Status 'up-to-date' "Installed $current is not older than $latest." @{installedVersion=$current; latestVersion=$latest}
    exit 0
}

try {
    Write-Status 'verifying' "Verifying immutable release $latest." @{installedVersion=$current; targetVersion=$latest}
    if ((Get-FreeDiskBytes) -lt 4GB) { throw 'Less than 4 GB free disk space; update was not started.' }
    Assert-ImmutableImage ([string]$manifest.images.backend) $repository 'backend'
    Assert-ImmutableImage ([string]$manifest.images.frontend) $repository 'frontend'
    Copy-Item $EnvFile (Join-Path $transaction 'env.before') -Force
    $backup = New-Backup $transaction $cfg
    if ($SimulateFailureAt -eq 'after-backup') { throw 'Simulated failure after backup.' }
    Set-EnvValues @{ DENTORA_VERSION=$latest; DENTORA_BACKEND_IMAGE=$manifest.images.backend; DENTORA_FRONTEND_IMAGE=$manifest.images.frontend }
    Write-Status 'installing' "Installing $latest after verified backup." @{installedVersion=$current; targetVersion=$latest; transaction=$transaction}
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
            if ((Test-Path (Join-Path $transaction 'database.sql')) -and (Test-Path (Join-Path $transaction 'storage.tar.gz'))) {
                Restore-Backup $transaction $old
            }
            Invoke-Docker @('compose','--env-file',$EnvFile,'-f',$Compose,'up','-d')
            Wait-Healthy
            Write-Status 'rolled-back' "Update failed and the previous release was restored: $reason" @{installedVersion=$old.DENTORA_VERSION; transaction=$transaction}
            exit 1
        }
    } catch { $reason += " Recovery also failed: $($_.Exception.Message)" }
    Write-Status 'failed' $reason @{installedVersion=$current; transaction=$transaction}
    throw
}
