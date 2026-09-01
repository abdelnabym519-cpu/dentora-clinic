param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backup", "restore", "recover")]
    [string]$Action,
    [string]$ArtifactPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$EnvFile = Join-Path $RepoRoot ".env.client"
$ComposeFile = Join-Path $RepoRoot "docker-compose.client.yml"
$JournalPath = Join-Path $RepoRoot ".dentora-restore-journal.json"
$BackupDir = Join-Path $RepoRoot "backups"
$TempRoot = if ([string]::IsNullOrWhiteSpace($env:TEMP)) { [IO.Path]::GetTempPath() } else { $env:TEMP }
$AppServices = @("backend", "frontend", "caddy")

function Invoke-Docker {
    param([string[]]$Arguments, [switch]$Capture)
    if ($Capture) {
        $output = & docker @Arguments 2>&1
        $code = $LASTEXITCODE
        if ($code -ne 0) { throw "Docker command failed with exit code $code." }
        return (($output | Out-String).Trim())
    }
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed with exit code $LASTEXITCODE." }
}

function Invoke-Compose {
    param([string[]]$Arguments, [switch]$Capture)
    $command = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile) + $Arguments
    return Invoke-Docker -Arguments $command -Capture:$Capture
}

function Assert-Administrator {
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw "Backup / Restore must be run from an Administrator terminal."
        }
        return
    }
    $uid = & id -u
    if ($LASTEXITCODE -ne 0 -or [string]$uid -ne "0") {
        throw "Backup / Restore requires root privileges on non-Windows validation hosts."
    }
}

function Assert-Preconditions {
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { throw ".env.client is missing." }
    if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) { throw "docker-compose.client.yml is missing." }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker is required." }
    Invoke-Docker -Arguments @("info") -Capture | Out-Null
    if ([IO.File]::ReadAllText($ComposeFile) -notmatch '(?m)^\s*STORAGE_BACKEND:\s*local\s*$') {
        throw "Backup / Restore supports the Dentora local storage deployment only."
    }
}

function Get-EnvValue {
    param([string]$Name)
    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
        if ($line.StartsWith("$Name=", [StringComparison]::Ordinal)) {
            return $line.Substring($Name.Length + 1)
        }
    }
    return ""
}

function Set-EnvValue {
    param([string]$Name, [string]$Value)
    $text = [IO.File]::ReadAllText($EnvFile)
    $pattern = '(?m)^' + [Regex]::Escape($Name) + '=.*$'
    $replacement = "$Name=$Value"
    if ([Regex]::IsMatch($text, $pattern)) {
        $text = [Regex]::Replace($text, $pattern, $replacement)
    } else {
        $text = $text.TrimEnd("`r", "`n") + [Environment]::NewLine + $replacement + [Environment]::NewLine
    }
    $tmp = "$EnvFile.$PID.tmp"
    [IO.File]::WriteAllText($tmp, $text, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $EnvFile -Force
}

function Assert-SafeIdentifier {
    param([string]$Value, [string]$Label)
    if ($Value -notmatch '^[A-Za-z0-9_]{1,48}$') { throw "$Label contains unsupported characters." }
}

function Assert-SafeVolumeName {
    param([string]$Value)
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$') { throw "Docker storage volume name is invalid." }
}

function Get-DatabaseSettings {
    $name = Get-EnvValue -Name "POSTGRES_DB"
    $user = Get-EnvValue -Name "POSTGRES_USER"
    if ([string]::IsNullOrWhiteSpace($name)) { $name = "dental_clinic" }
    if ([string]::IsNullOrWhiteSpace($user)) { $user = "dental" }
    Assert-SafeIdentifier -Value $name -Label "Database name"
    Assert-SafeIdentifier -Value $user -Label "Database user"
    return @{ Name = $name; User = $user }
}

function Get-AppVersion {
    $path = Join-Path (Join-Path $RepoRoot "backend") "pyproject.toml"
    $text = [IO.File]::ReadAllText($path)
    $match = [Regex]::Match($text, '(?m)^version\s*=\s*"([^"]+)"\s*$')
    if (-not $match.Success) { throw "Could not determine the installed Dentora version." }
    return $match.Groups[1].Value
}

function Get-SchemaFingerprint {
    param([string[]]$Revisions)
    $normalized = @(
        $Revisions |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    if ($normalized.Count -eq 0) { throw "Dentora schema revision set is empty." }
    foreach ($revision in $normalized) {
        if ($revision -notmatch '^[A-Za-z0-9_-]{4,128}$') {
            throw "Dentora schema revision set contains an invalid revision."
        }
    }
    $canonical = $normalized -join "`n"
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))
    } finally {
        $sha256.Dispose()
    }
    return "heads-$(-join ($digest | ForEach-Object { $_.ToString('x2') }))"
}

function Get-ExpectedSchemaRevision {
    $output = Invoke-Compose -Arguments @("run", "--rm", "--no-deps", "--entrypoint", "alembic", "backend", "heads") -Capture
    $matches = [Regex]::Matches(
        $output,
        '(?m)^([A-Za-z0-9_-]+)(?:\s+\([A-Za-z0-9_-]+\))?\s+\((?:effective )?head\)\s*$'
    )
    return Get-SchemaFingerprint -Revisions @($matches | ForEach-Object { $_.Groups[1].Value })
}

function Get-DatabaseSchemaRevision {
    param([string]$Database, [string]$User)
    Assert-SafeIdentifier -Value $Database -Label "Database name"
    Assert-SafeIdentifier -Value $User -Label "Database user"
    $output = Invoke-Compose -Arguments @(
        "run", "--rm", "--no-deps", "-e", "DENTORA_SCHEMA_DATABASE=$Database",
        "--entrypoint", "sh", "backend", "-c",
        'export DATABASE_URL="${DATABASE_URL%/*}/$DENTORA_SCHEMA_DATABASE"; exec alembic current'
    ) -Capture
    $matches = [Regex]::Matches(
        $output,
        '(?m)^([A-Za-z0-9_-]+)(?:\s+\([A-Za-z0-9_-]+\))?\s+\((?:effective )?head\)\s*$'
    )
    return Get-SchemaFingerprint -Revisions @($matches | ForEach-Object { $_.Groups[1].Value })
}

function Get-RunningServices {
    $output = Invoke-Compose -Arguments @("ps", "--status", "running", "--services") -Capture
    if ([string]::IsNullOrWhiteSpace($output)) { return @() }
    return @($output -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Stop-AppServices {
    param([string[]]$RunningServices)
    $targets = @($AppServices | Where-Object { $RunningServices -contains $_ })
    if ($targets.Count -gt 0) { Invoke-Compose -Arguments (@("stop") + $targets) }
}

function Start-AppServices {
    param([string[]]$RunningServices, [switch]$Recreate)
    $targets = @($AppServices | Where-Object { $RunningServices -contains $_ })
    if ($targets.Count -eq 0) { return }
    if ($Recreate) {
        Invoke-Compose -Arguments (@("up", "-d", "--force-recreate") + $targets)
    } else {
        Invoke-Compose -Arguments (@("start") + $targets)
    }
}

function Get-StorageVolumeName {
    $name = Get-EnvValue -Name "DENTORA_STORAGE_VOLUME"
    if ([string]::IsNullOrWhiteSpace($name)) { $name = "dentora-client-storage-data" }
    Assert-SafeVolumeName -Value $name
    return $name
}

function Protect-BackupDirectory {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        if (-not (Get-Command icacls.exe -ErrorAction SilentlyContinue)) { throw "icacls.exe is required." }
        & icacls.exe $BackupDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not restrict Dentora backup directory permissions." }
        return
    }
    & chmod 700 $BackupDir
    if ($LASTEXITCODE -ne 0) { throw "Could not restrict Dentora backup directory permissions." }
}

function New-BackupId {
    return "dentora-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
}

function Invoke-ArtifactCli {
    param([string]$Stage, [string[]]$Arguments)
    $mount = "${Stage}:/backup"
    $command = @(
        "run", "--rm", "--no-deps", "--user", "0:0", "-v", $mount,
        "--entrypoint", "python", "backend", "-m", "app.cli.backup_artifact"
    ) + $Arguments
    Invoke-Compose -Arguments $command | Out-Null
}

function Test-ZipLayout {
    param([string]$Path)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $required = @("manifest.json", "database.dump", "storage.tar")
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if ([string]::IsNullOrWhiteSpace($entry.Name)) { throw "Backup ZIP contains an unexpected directory." }
            if ($name.StartsWith('/') -or $name.Contains('../') -or $name -eq '..') { throw "Backup ZIP contains an unsafe path." }
            if ($required -notcontains $name) { throw "Backup ZIP contains an unexpected file." }
            if (-not $seen.Add($name)) { throw "Backup ZIP contains duplicate files." }
        }
        if ($seen.Count -ne $required.Count) { throw "Backup ZIP is incomplete." }
        foreach ($name in $required) { if (-not $seen.Contains($name)) { throw "Backup ZIP is incomplete." } }
    } finally {
        $archive.Dispose()
    }
}

function Expand-ValidatedZip {
    param([string]$ZipPath, [string]$Destination)
    Test-ZipLayout -Path $ZipPath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
}

function Write-RestoreJournal {
    param([hashtable]$Journal)
    $tmp = "$JournalPath.$PID.tmp"
    [IO.File]::WriteAllText($tmp, (($Journal | ConvertTo-Json -Depth 5) + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $JournalPath -Force
}

function Read-RestoreJournal {
    if (-not (Test-Path -LiteralPath $JournalPath -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $JournalPath -Raw | ConvertFrom-Json }
    catch { throw "Restore journal is unreadable. Dentora remains fail-closed." }
}

function Invoke-PostgresSql {
    param([string]$User, [string]$Sql)
    Invoke-Compose -Arguments @("exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-U", $User, "-d", "postgres", "-c", $Sql)
}

function Test-DatabaseExists {
    param([string]$User, [string]$Database)
    Assert-SafeIdentifier -Value $Database -Label "Database name"
    $output = Invoke-Compose -Arguments @(
        "exec", "-T", "db", "psql", "-U", $User, "-d", "postgres", "-Atc",
        "SELECT 1 FROM pg_database WHERE datname='$Database';"
    ) -Capture
    return $output.Trim() -eq "1"
}

function Remove-DatabaseIfExists {
    param([string]$User, [string]$Database)
    if (-not (Test-DatabaseExists -User $User -Database $Database)) { return }
    Invoke-PostgresSql -User $User -Sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$Database' AND pid <> pg_backend_pid();"
    Invoke-PostgresSql -User $User -Sql "DROP DATABASE $Database;"
}

function Wait-DentoraHealth {
    param([string]$PublicUrl)
    $healthUrl = $PublicUrl.TrimEnd('/') + "/health/ready"
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 4
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    throw "Dentora did not become ready after restore."
}

function Invoke-BackupInternal {
    param([switch]$PreRestore)
    if ((Test-Path -LiteralPath $JournalPath) -and -not $PreRestore) { throw "Recover the interrupted restore before backup." }
    Protect-BackupDirectory
    $running = @(Get-RunningServices)
    if ($running -notcontains "db") { throw "Dentora database is not running." }
    $db = Get-DatabaseSettings
    $version = Get-AppVersion
    $schema = Get-ExpectedSchemaRevision
    if ((Get-DatabaseSchemaRevision -Database $db.Name -User $db.User) -ne $schema) { throw "Database schema is not at the installed Alembic head." }

    $backupId = New-BackupId
    $createdAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
    $stage = Join-Path (Join-Path $TempRoot "DentoraBackup") $backupId
    $partial = Join-Path $BackupDir "$backupId.zip.partial"
    $final = Join-Path $BackupDir "$backupId.zip"
    $containerDump = "/tmp/$backupId.dump"
    $stopped = $false
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    try {
        Stop-AppServices -RunningServices $running
        $stopped = $true
        Invoke-Compose -Arguments @("exec", "-T", "db", "pg_dump", "-U", $db.User, "-d", $db.Name, "-Fc", "-f", $containerDump)
        Invoke-Compose -Arguments @("exec", "-T", "db", "pg_restore", "--list", $containerDump) -Capture | Out-Null
        Invoke-Compose -Arguments @("cp", "db:$containerDump", (Join-Path $stage "database.dump"))
        Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDump) -Capture | Out-Null

        $mount = "${stage}:/backup"
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "--user", "0:0", "-v", $mount, "--entrypoint", "sh", "backend", "-c",
            "set -eu; tar --exclude='./license' --exclude='./license/*' -C /app/storage -cf /backup/storage.tar ."
        )
        Invoke-ArtifactCli -Stage $stage -Arguments @(
            "create", "--root", "/backup", "--backup-id", $backupId,
            "--created-at-utc", $createdAt, "--app-version", $version, "--schema-revision", $schema
        )
        Invoke-ArtifactCli -Stage $stage -Arguments @(
            "validate", "--root", "/backup", "--app-version", $version, "--schema-revision", $schema
        )

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        [IO.Compression.ZipFile]::CreateFromDirectory($stage, $partial, [IO.Compression.CompressionLevel]::Optimal, $false)
        Test-ZipLayout -Path $partial
        if (Test-Path -LiteralPath $final) { throw "Backup destination already exists; refusing to overwrite it." }
        Move-Item -LiteralPath $partial -Destination $final
        return $final
    } finally {
        try { Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDump) -Capture | Out-Null } catch { }
        if ($stopped) { try { Start-AppServices -RunningServices $running } catch { Write-Warning "Could not restart every service after backup." } }
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Recover-InterruptedRestore {
    $journal = Read-RestoreJournal
    if ($null -eq $journal) { return }
    $user = [string]$journal.db_user
    $live = [string]$journal.live_db
    $temp = [string]$journal.temp_db
    $rollback = [string]$journal.rollback_db
    $oldVolume = [string]$journal.old_storage_volume
    $newVolume = [string]$journal.new_storage_volume
    $phase = [string]$journal.phase
    $running = @($journal.running_services | ForEach-Object { [string]$_ })
    foreach ($item in @(@($user, "Database user"), @($live, "Database name"), @($temp, "Temporary database"), @($rollback, "Rollback database"))) {
        Assert-SafeIdentifier -Value $item[0] -Label $item[1]
    }
    Assert-SafeVolumeName -Value $oldVolume
    Assert-SafeVolumeName -Value $newVolume

    if ($phase -eq "committed") {
        Remove-DatabaseIfExists -User $user -Database $rollback
        Remove-Item -LiteralPath $JournalPath -Force
        return
    }

    Stop-AppServices -RunningServices @(Get-RunningServices)
    try { Invoke-Compose -Arguments @("rm", "-f", "backend", "frontend", "caddy") -Capture | Out-Null } catch { }
    Set-EnvValue -Name "DENTORA_STORAGE_VOLUME" -Value $oldVolume
    if (Test-DatabaseExists -User $user -Database $rollback) {
        Invoke-PostgresSql -User $user -Sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$live' AND pid <> pg_backend_pid();"
        Remove-DatabaseIfExists -User $user -Database $live
        Invoke-PostgresSql -User $user -Sql "ALTER DATABASE $rollback RENAME TO $live;"
    }
    Remove-DatabaseIfExists -User $user -Database $temp
    try { Invoke-Docker -Arguments @("volume", "rm", $newVolume) -Capture | Out-Null } catch { }
    Start-AppServices -RunningServices $running -Recreate
    Remove-Item -LiteralPath $JournalPath -Force
}

function Invoke-RestoreInternal {
    param([string]$BackupPath)
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) { throw "Backup file does not exist." }
    $resolved = (Resolve-Path -LiteralPath $BackupPath).Path
    if ([IO.Path]::GetExtension($resolved) -ne ".zip") { throw "Restore accepts only a Dentora backup ZIP." }
    if (Test-Path -LiteralPath $JournalPath) { Recover-InterruptedRestore }

    $running = @(Get-RunningServices)
    foreach ($required in @("db", "backend", "frontend", "caddy")) {
        if ($running -notcontains $required) { throw "Dentora must be fully running before restore." }
    }
    $db = Get-DatabaseSettings
    $version = Get-AppVersion
    $schema = Get-ExpectedSchemaRevision
    $stageName = "restore-" + [Guid]::NewGuid().ToString("N")
    $stage = Join-Path (Join-Path $TempRoot "DentoraRestore") $stageName
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    try {
        Expand-ValidatedZip -ZipPath $resolved -Destination $stage
        Invoke-ArtifactCli -Stage $stage -Arguments @(
            "validate", "--root", "/backup", "--app-version", $version, "--schema-revision", $schema
        )
        $manifest = Get-Content -LiteralPath (Join-Path $stage "manifest.json") -Raw | ConvertFrom-Json
        $backupId = [string]$manifest.backup_id
        if ($backupId -notmatch '^[A-Za-z0-9._-]{8,96}$') { throw "Backup identifier is invalid." }
        $mount = "${stage}:/backup:ro"
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "-v", $mount,
            "--entrypoint", "pg_restore", "db", "--list", "/backup/database.dump"
        ) -Capture | Out-Null

        $safetyBackup = Invoke-BackupInternal -PreRestore
        if (-not (Test-Path -LiteralPath $safetyBackup -PathType Leaf)) { throw "Pre-restore safety backup failed." }

        $nonce = [Guid]::NewGuid().ToString("N").Substring(0, 10)
        $tempDb = "dentora_restore_$nonce"
        $rollbackDb = "dentora_rollback_$nonce"
        $oldVolume = Get-StorageVolumeName
        $newVolume = "dentora-restore-storage-$nonce"
        Assert-SafeVolumeName -Value $newVolume
        $existingVolume = Invoke-Docker -Arguments @("volume", "ls", "-q", "--filter", "name=$newVolume") -Capture
        if (-not [string]::IsNullOrWhiteSpace($existingVolume)) { throw "Restore storage volume already exists; refusing to overwrite it." }

        $journal = @{
            version = 1; phase = "prepared"; backup_id = $backupId; db_user = $db.User;
            live_db = $db.Name; temp_db = $tempDb; rollback_db = $rollbackDb;
            old_storage_volume = $oldVolume; new_storage_volume = $newVolume; running_services = $running
        }
        Write-RestoreJournal -Journal $journal
        Stop-AppServices -RunningServices $running

        Remove-DatabaseIfExists -User $db.User -Database $tempDb
        Remove-DatabaseIfExists -User $db.User -Database $rollbackDb
        Invoke-PostgresSql -User $db.User -Sql "CREATE DATABASE $tempDb;"
        $containerDump = "/tmp/$stageName.dump"
        try {
            Invoke-Compose -Arguments @("cp", (Join-Path $stage "database.dump"), "db:$containerDump")
            Invoke-Compose -Arguments @(
                "exec", "-T", "db", "pg_restore", "-U", $db.User, "-d", $tempDb,
                "--no-owner", "--no-privileges", "--exit-on-error", $containerDump
            )
        } finally {
            try { Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDump) -Capture | Out-Null } catch { }
        }
        $restoredSchema = Get-DatabaseSchemaRevision -Database $tempDb -User $db.User
        if ($restoredSchema -ne $schema -or $restoredSchema -ne [string]$manifest.schema_revision) {
            throw "Restored database schema is incompatible."
        }

        Invoke-Docker -Arguments @(
            "volume", "create", "--label", "dentora.role=restore-storage",
            "--label", "dentora.backup_id=$backupId", $newVolume
        ) -Capture | Out-Null
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "--user", "0:0", "-v", $mount, "-v", "${newVolume}:/restore",
            "--entrypoint", "sh", "backend", "-c",
            "set -eu; tar -xf /backup/storage.tar -C /restore; if [ -d /app/storage/license ]; then mkdir -p /restore/license; cp -a /app/storage/license/. /restore/license/; fi; chown -R 1000:1000 /restore"
        )

        Invoke-PostgresSql -User $db.User -Sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$($db.Name)' AND pid <> pg_backend_pid();"
        Invoke-PostgresSql -User $db.User -Sql "ALTER DATABASE $($db.Name) RENAME TO $rollbackDb;"
        Invoke-PostgresSql -User $db.User -Sql "ALTER DATABASE $tempDb RENAME TO $($db.Name);"
        $journal["phase"] = "database_swapped"
        Write-RestoreJournal -Journal $journal

        Set-EnvValue -Name "DENTORA_STORAGE_VOLUME" -Value $newVolume
        $journal["phase"] = "storage_switched"
        Write-RestoreJournal -Journal $journal
        try { Invoke-Compose -Arguments @("rm", "-f", "backend", "frontend", "caddy") -Capture | Out-Null } catch { }
        Start-AppServices -RunningServices $running -Recreate
        $publicUrl = Get-EnvValue -Name "PUBLIC_URL"
        if ([string]::IsNullOrWhiteSpace($publicUrl)) { $publicUrl = "http://localhost" }
        Wait-DentoraHealth -PublicUrl $publicUrl

        $journal["phase"] = "committed"
        Write-RestoreJournal -Journal $journal
        Remove-DatabaseIfExists -User $db.User -Database $rollbackDb
        Remove-Item -LiteralPath $JournalPath -Force
        Write-Host "Restore succeeded."
        Write-Host "Backup ID: $backupId"
        Write-Host "Safety backup: $safetyBackup"
        Write-Host "Previous storage volume retained for manual disaster recovery: $oldVolume"
    } catch {
        $original = $_
        if (Test-Path -LiteralPath $JournalPath) {
            try { Recover-InterruptedRestore }
            catch { throw "Restore failed and automatic rollback could not complete. Dentora remains fail-closed. Original error: $($original.Exception.Message)" }
        }
        throw $original
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function New-DentoraMutex {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($RepoRoot.ToLowerInvariant())
        $hash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').Substring(0, 24)
    } finally { $sha.Dispose() }
    $mutex = New-Object Threading.Mutex($false, "DentoraBackupRestore_$hash")
    try { $acquired = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) {
        $mutex.Dispose()
        throw "Another Dentora Backup / Restore operation is already running."
    }
    return $mutex
}

Assert-Administrator
Assert-Preconditions
$operationMutex = New-DentoraMutex
try {
    switch ($Action) {
        "backup" {
            $result = Invoke-BackupInternal
            Write-Host "Backup succeeded."
            Write-Host "Artifact: $result"
        }
        "restore" {
            if ([string]::IsNullOrWhiteSpace($ArtifactPath)) { throw "Restore requires the path to a Dentora backup ZIP." }
            Invoke-RestoreInternal -BackupPath $ArtifactPath
        }
        "recover" {
            if (-not (Test-Path -LiteralPath $JournalPath)) { Write-Host "No interrupted Dentora restore was found." }
            else { Recover-InterruptedRestore; Write-Host "Interrupted restore was recovered safely." }
        }
    }
} finally {
    try { $operationMutex.ReleaseMutex() } catch { }
    $operationMutex.Dispose()
}
