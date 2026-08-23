param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backup", "restore", "recover")]
    [string]$Action,

    [Parameter(Mandatory = $false)]
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
$AppServices = @("backend", "frontend", "caddy")

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Capture
    )

    if ($Capture) {
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "Docker command failed with exit code $exitCode."
        }
        return (($output | Out-String).Trim())
    }

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Capture
    )

    $prefix = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)
    return Invoke-Docker -Arguments ($prefix + $Arguments) -Capture:$Capture
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Backup / Restore must be run from an Administrator terminal."
    }
}

function Assert-Preconditions {
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        throw ".env.client is missing. Run START_DENTORA.bat first."
    }
    if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
        throw "docker-compose.client.yml is missing."
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is not installed or docker.exe is not in PATH."
    }
    Invoke-Docker -Arguments @("info") -Capture | Out-Null

    $composeText = [IO.File]::ReadAllText($ComposeFile)
    if ($composeText -notmatch '(?m)^\s*STORAGE_BACKEND:\s*local\s*$') {
        throw "Backup / Restore supports the Dentora client local storage backend only."
    }
}

function Get-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
        if ($line.StartsWith("$Name=", [StringComparison]::Ordinal)) {
            return $line.Substring($Name.Length + 1)
        }
    }
    return ""
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

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
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -notmatch '^[A-Za-z0-9_]{1,48}$') {
        throw "$Label contains unsupported characters."
    }
}

function Assert-SafeVolumeName {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$') {
        throw "Docker storage volume name is invalid."
    }
}

function Get-AppVersion {
    $path = Join-Path $RepoRoot "backend\pyproject.toml"
    $match = [Regex]::Match([IO.File]::ReadAllText($path), '(?m)^version\s*=\s*"([^"]+)"\s*$')
    if (-not $match.Success) {
        throw "Could not determine the installed Dentora version."
    }
    return $match.Groups[1].Value
}

function Get-ExpectedSchemaRevision {
    $output = Invoke-Compose -Arguments @(
        "run", "--rm", "--no-deps", "--entrypoint", "alembic", "backend", "heads"
    ) -Capture
    $matches = [Regex]::Matches($output, '(?m)^([A-Za-z0-9_-]+)\s+\(head\)\s*$')
    if ($matches.Count -ne 1) {
        throw "Dentora must have exactly one Alembic head before Backup / Restore."
    }
    return $matches[0].Groups[1].Value
}

function Get-DatabaseSchemaRevision {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$User
    )

    Assert-SafeIdentifier -Value $Database -Label "Database name"
    Assert-SafeIdentifier -Value $User -Label "Database user"
    $output = Invoke-Compose -Arguments @(
        "exec", "-T", "db", "psql", "-U", $User, "-d", $Database,
        "-Atc", "SELECT version_num FROM alembic_version;"
    ) -Capture
    $revision = $output.Trim()
    if ($revision -notmatch '^[A-Za-z0-9_-]{4,128}$') {
        throw "Database Alembic revision is missing or invalid."
    }
    return $revision
}

function Get-RunningServices {
    $output = Invoke-Compose -Arguments @("ps", "--status", "running", "--services") -Capture
    if ([string]::IsNullOrWhiteSpace($output)) {
        return @()
    }
    return @($output -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Stop-RunningAppServices {
    param([string[]]$RunningServices)
    $targets = @($AppServices | Where-Object { $RunningServices -contains $_ })
    if ($targets.Count -gt 0) {
        Invoke-Compose -Arguments (@("stop") + $targets)
    }
}

function Start-PreviouslyRunningAppServices {
    param([string[]]$RunningServices)
    $targets = @($AppServices | Where-Object { $RunningServices -contains $_ })
    if ($targets.Count -gt 0) {
        Invoke-Compose -Arguments (@("start") + $targets)
    }
}

function Recreate-PreviouslyRunningAppServices {
    param([string[]]$RunningServices)
    $targets = @($AppServices | Where-Object { $RunningServices -contains $_ })
    if ($targets.Count -gt 0) {
        Invoke-Compose -Arguments (@("up", "-d", "--force-recreate") + $targets)
    }
}

function Get-StorageVolumeName {
    $configured = Get-EnvValue -Name "DENTORA_STORAGE_VOLUME"
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = "dentora-client-storage-data"
    }
    Assert-SafeVolumeName -Value $configured
    return $configured
}

function Protect-BackupDirectory {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    if (-not (Get-Command icacls.exe -ErrorAction SilentlyContinue)) {
        throw "icacls.exe is required to protect Dentora backup files."
    }
    & icacls.exe $BackupDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restrict Dentora backup directory permissions."
    }
}

function New-BackupId {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    return "dentora-$stamp-$suffix"
}

function Invoke-ArtifactCli {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $mount = "${Stage}:/backup"
    Invoke-Compose -Arguments @(
        "run", "--rm", "--no-deps", "-v", $mount,
        "--entrypoint", "python", "backend", "-m", "app.cli.backup_artifact"
    ) + $Arguments
}

function Test-ZipLayout {
    param([Parameter(Mandatory = $true)][string]$Path)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $required = @("manifest.json", "database.dump", "storage.tar")
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if ([string]::IsNullOrWhiteSpace($entry.Name)) {
                throw "Backup ZIP contains an unexpected directory."
            }
            if ($name.StartsWith('/') -or $name.Contains('../') -or $name -eq '..') {
                throw "Backup ZIP contains an unsafe path."
            }
            if ($required -notcontains $name) {
                throw "Backup ZIP contains an unexpected file."
            }
            if (-not $seen.Add($name)) {
                throw "Backup ZIP contains duplicate files."
            }
        }
        if ($seen.Count -ne $required.Count) {
            throw "Backup ZIP is incomplete."
        }
        foreach ($name in $required) {
            if (-not $seen.Contains($name)) {
                throw "Backup ZIP is incomplete."
            }
        }
    } finally {
        $archive.Dispose()
    }
}

function Expand-ValidatedZip {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    Test-ZipLayout -Path $ZipPath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
}

function Write-RestoreJournal {
    param([Parameter(Mandatory = $true)][hashtable]$Journal)
    $tmp = "$JournalPath.$PID.tmp"
    $json = $Journal | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($tmp, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $JournalPath -Force
}

function Read-RestoreJournal {
    if (-not (Test-Path -LiteralPath $JournalPath -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $JournalPath -Raw | ConvertFrom-Json
    } catch {
        throw "Restore journal is unreadable. Dentora remains fail-closed until it is recovered manually."
    }
}

function Invoke-PostgresSql {
    param(
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Sql
    )
    Invoke-Compose -Arguments @("exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1", "-U", $User, "-d", "postgres", "-c", $Sql)
}

function Test-DatabaseExists {
    param(
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Database
    )
    Assert-SafeIdentifier -Value $Database -Label "Database name"
    $output = Invoke-Compose -Arguments @(
        "exec", "-T", "db", "psql", "-U", $User, "-d", "postgres", "-Atc",
        "SELECT 1 FROM pg_database WHERE datname='$Database';"
    ) -Capture
    return $output.Trim() -eq "1"
}

function Remove-DatabaseIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Database
    )
    Assert-SafeIdentifier -Value $Database -Label "Database name"
    if (Test-DatabaseExists -User $User -Database $Database) {
        Invoke-PostgresSql -User $User -Sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$Database' AND pid <> pg_backend_pid();"
        Invoke-PostgresSql -User $User -Sql "DROP DATABASE $Database;"
    }
}

function Wait-DentoraHealth {
    param([Parameter(Mandatory = $true)][string]$PublicUrl)
    $healthUrl = $PublicUrl.TrimEnd('/') + "/health"
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 4
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
            # Retry while services recreate. TLS validation is intentionally not bypassed.
        }
        Start-Sleep -Seconds 2
    }
    throw "Dentora did not become healthy after restore."
}

function Invoke-BackupInternal {
    param([switch]$PreRestore)

    if ((Test-Path -LiteralPath $JournalPath) -and -not $PreRestore) {
        throw "An interrupted restore journal exists. Recover it before creating a backup."
    }

    Protect-BackupDirectory
    $running = @(Get-RunningServices)
    if ($running -notcontains "db") {
        throw "Dentora database is not running. Start Dentora before creating a backup."
    }

    $dbName = Get-EnvValue -Name "POSTGRES_DB"
    $dbUser = Get-EnvValue -Name "POSTGRES_USER"
    if ([string]::IsNullOrWhiteSpace($dbName)) { $dbName = "dental_clinic" }
    if ([string]::IsNullOrWhiteSpace($dbUser)) { $dbUser = "dental" }
    Assert-SafeIdentifier -Value $dbName -Label "Database name"
    Assert-SafeIdentifier -Value $dbUser -Label "Database user"

    $appVersion = Get-AppVersion
    $expectedSchema = Get-ExpectedSchemaRevision
    $liveSchema = Get-DatabaseSchemaRevision -Database $dbName -User $dbUser
    if ($liveSchema -ne $expectedSchema) {
        throw "Database schema is not at the installed Dentora Alembic head."
    }

    $backupId = New-BackupId
    $createdAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ")
    $stage = Join-Path $env:TEMP "DentoraBackup\$backupId"
    $partial = Join-Path $BackupDir "$backupId.zip.partial"
    $final = Join-Path $BackupDir "$backupId.zip"
    $dbContainerPath = "/tmp/$backupId.dump"
    $stopped = $false

    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    try {
        Stop-RunningAppServices -RunningServices $running
        $stopped = $true

        Invoke-Compose -Arguments @(
            "exec", "-T", "db", "pg_dump", "-U", $dbUser, "-d", $dbName,
            "-Fc", "-f", $dbContainerPath
        )
        Invoke-Compose -Arguments @("exec", "-T", "db", "pg_restore", "--list", $dbContainerPath) -Capture | Out-Null
        Invoke-Compose -Arguments @("cp", "db:$dbContainerPath", (Join-Path $stage "database.dump"))
        Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $dbContainerPath)

        $mount = "${stage}:/backup"
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "-v", $mount, "--entrypoint", "sh", "backend", "-c",
            "set -eu; tar --exclude='./license' --exclude='./license/*' -C /app/storage -cf /backup/storage.tar ."
        )

        Invoke-ArtifactCli -Stage $stage -Arguments @(
            "create", "--root", "/backup", "--backup-id", $backupId,
            "--created-at-utc", $createdAt, "--app-version", $appVersion,
            "--schema-revision", $expectedSchema
        )
        Invoke-ArtifactCli -Stage $stage -Arguments @(
            "validate", "--root", "/backup", "--app-version", $appVersion,
            "--schema-revision", $expectedSchema
        )

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        [IO.Compression.ZipFile]::CreateFromDirectory(
            $stage,
            $partial,
            [IO.Compression.CompressionLevel]::Optimal,
            $false
        )
        Test-ZipLayout -Path $partial
        if (Test-Path -LiteralPath $final) {
            throw "Backup destination already exists; refusing to overwrite it."
        }
        Move-Item -LiteralPath $partial -Destination $final
        return $final
    } finally {
        try { Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $dbContainerPath) -Capture | Out-Null } catch { }
        if ($stopped) {
            try { Start-PreviouslyRunningAppServices -RunningServices $running } catch { Write-Warning "Could not restart every service after backup." }
        }
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Recover-InterruptedRestore {
    $journal = Read-RestoreJournal
    if ($null -eq $journal) {
        return
    }

    $dbUser = [string]$journal.db_user
    $liveDb = [string]$journal.live_db
    $tempDb = [string]$journal.temp_db
    $rollbackDb = [string]$journal.rollback_db
    $oldVolume = [string]$journal.old_storage_volume
    $newVolume = [string]$journal.new_storage_volume
    $phase = [string]$journal.phase
    $running = @($journal.running_services | ForEach-Object { [string]$_ })

    Assert-SafeIdentifier -Value $dbUser -Label "Database user"
    Assert-SafeIdentifier -Value $liveDb -Label "Database name"
    Assert-SafeIdentifier -Value $tempDb -Label "Temporary database name"
    Assert-SafeIdentifier -Value $rollbackDb -Label "Rollback database name"
    Assert-SafeVolumeName -Value $oldVolume
    Assert-SafeVolumeName -Value $newVolume

    if ($phase -eq "committed") {
        Remove-DatabaseIfExists -User $dbUser -Database $rollbackDb
        Remove-Item -LiteralPath $JournalPath -Force
        return
    }

    Stop-RunningAppServices -RunningServices @(Get-RunningServices)
    try { Invoke-Compose -Arguments @("rm", "-f", "backend", "frontend", "caddy") -Capture | Out-Null } catch { }

    Set-EnvValue -Name "DENTORA_STORAGE_VOLUME" -Value $oldVolume

    if (Test-DatabaseExists -User $dbUser -Database $rollbackDb) {
        Invoke-PostgresSql -User $dbUser -Sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$liveDb' AND pid <> pg_backend_pid();"
        Remove-DatabaseIfExists -User $dbUser -Database $liveDb
        Invoke-PostgresSql -User $dbUser -Sql "ALTER DATABASE $rollbackDb RENAME TO $liveDb;"
    }
    Remove-DatabaseIfExists -User $dbUser -Database $tempDb

    try { Invoke-Docker -Arguments @("volume", "rm", $newVolume) -Capture | Out-Null } catch { }
    Recreate-PreviouslyRunningAppServices -RunningServices $running
    Remove-Item -LiteralPath $JournalPath -Force
}

function Invoke-RestoreInternal {
    param([Parameter(Mandatory = $true)][string]$BackupPath)

    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
        throw "Backup file does not exist."
    }
    $resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
    if ([IO.Path]::GetExtension($resolvedBackup) -ne ".zip") {
        throw "Dentora restore accepts only a validated .zip backup artifact."
    }

    if (Test-Path -LiteralPath $JournalPath) {
        Recover-InterruptedRestore
    }

    $running = @(Get-RunningServices)
    foreach ($required in @("db", "backend", "frontend", "caddy")) {
        if ($running -notcontains $required) {
            throw "Dentora must be fully running before restore so a safety backup can be created."
        }
    }

    $dbName = Get-EnvValue -Name "POSTGRES_DB"
    $dbUser = Get-EnvValue -Name "POSTGRES_USER"
    if ([string]::IsNullOrWhiteSpace($dbName)) { $dbName = "dental_clinic" }
    if ([string]::IsNullOrWhiteSpace($dbUser)) { $dbUser = "dental" }
    Assert-SafeIdentifier -Value $dbName -Label "Database name"
    Assert-SafeIdentifier -Value $dbUser -Label "Database user"

    $appVersion = Get-AppVersion
    $expectedSchema = Get-ExpectedSchemaRevision
    $stageName = "restore-" + [Guid]::NewGuid().ToString("N")
    $stage = Join-Path $env:TEMP "DentoraRestore\$stageName"
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    try {
        Expand-ValidatedZip -ZipPath $resolvedBackup -Destination $stage
        Invoke-ArtifactCli -Stage $stage -Arguments @(
            "validate", "--root", "/backup", "--app-version", $appVersion,
            "--schema-revision", $expectedSchema
        )
        $manifest = Get-Content -LiteralPath (Join-Path $stage "manifest.json") -Raw | ConvertFrom-Json
        $backupId = [string]$manifest.backup_id
        if ($backupId -notmatch '^[A-Za-z0-9._-]{8,96}$') {
            throw "Backup identifier is invalid."
        }

        $mount = "${stage}:/backup:ro"
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "-v", $mount,
            "--entrypoint", "pg_restore", "db", "--list", "/backup/database.dump"
        ) -Capture | Out-Null

        $safetyBackup = Invoke-BackupInternal -PreRestore
        if (-not (Test-Path -LiteralPath $safetyBackup -PathType Leaf)) {
            throw "Pre-restore safety backup was not created."
        }

        $nonce = [Guid]::NewGuid().ToString("N").Substring(0, 10)
        $tempDb = "dentora_restore_$nonce"
        $rollbackDb = "dentora_rollback_$nonce"
        $oldVolume = Get-StorageVolumeName
        $newVolume = "dentora-restore-storage-$nonce"
        Assert-SafeVolumeName -Value $newVolume

        $journal = @{
            version = 1
            phase = "prepared"
            backup_id = $backupId
            db_user = $dbUser
            live_db = $dbName
            temp_db = $tempDb
            rollback_db = $rollbackDb
            old_storage_volume = $oldVolume
            new_storage_volume = $newVolume
            running_services = $running
        }
        Write-RestoreJournal -Journal $journal

        Stop-RunningAppServices -RunningServices $running

        Remove-DatabaseIfExists -User $dbUser -Database $tempDb
        Remove-DatabaseIfExists -User $dbUser -Database $rollbackDb
        Invoke-PostgresSql -User $dbUser -Sql "CREATE DATABASE $tempDb;"

        $dbContainerPath = "/tmp/$stageName.dump"
        try {
            Invoke-Compose -Arguments @("cp", (Join-Path $stage "database.dump"), "db:$dbContainerPath")
            Invoke-Compose -Arguments @(
                "exec", "-T", "db", "pg_restore", "-U", $dbUser, "-d", $tempDb,
                "--no-owner", "--no-privileges", "--exit-on-error", $dbContainerPath
            )
        } finally {
            try { Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $dbContainerPath) -Capture | Out-Null } catch { }
        }

        $restoredSchema = Get-DatabaseSchemaRevision -Database $tempDb -User $dbUser
        if ($restoredSchema -ne $expectedSchema -or $restoredSchema -ne [string]$manifest.schema_revision) {
            throw "Restored database schema does not match the validated backup and installed Dentora schema."
        }

        Invoke-Docker -Arguments @(
            "volume", "create", "--label", "dentora.role=restore-storage",
            "--label", "dentora.backup_id=$backupId", $newVolume
        ) -Capture | Out-Null
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "-v", $mount, "-v", "${newVolume}:/restore",
            "--entrypoint", "sh", "backend", "-c",
            "set -eu; tar -xf /backup/storage.tar -C /restore; if [ -d /app/storage/license ]; then mkdir -p /restore/license; cp -a /app/storage/license/. /restore/license/; fi"
        )

        Invoke-PostgresSql -User $dbUser -Sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$dbName' AND pid <> pg_backend_pid();"
        Invoke-PostgresSql -User $dbUser -Sql "ALTER DATABASE $dbName RENAME TO $rollbackDb;"
        Invoke-PostgresSql -User $dbUser -Sql "ALTER DATABASE $tempDb RENAME TO $dbName;"
        $journal.phase = "database_swapped"
        Write-RestoreJournal -Journal $journal

        Set-EnvValue -Name "DENTORA_STORAGE_VOLUME" -Value $newVolume
        $journal.phase = "storage_switched"
        Write-RestoreJournal -Journal $journal

        try { Invoke-Compose -Arguments @("rm", "-f", "backend", "frontend", "caddy") -Capture | Out-Null } catch { }
        Recreate-PreviouslyRunningAppServices -RunningServices $running
        $publicUrl = Get-EnvValue -Name "PUBLIC_URL"
        if ([string]::IsNullOrWhiteSpace($publicUrl)) { $publicUrl = "http://localhost" }
        Wait-DentoraHealth -PublicUrl $publicUrl

        $journal.phase = "committed"
        Write-RestoreJournal -Journal $journal
        Remove-DatabaseIfExists -User $dbUser -Database $rollbackDb
        Remove-Item -LiteralPath $JournalPath -Force

        Write-Host "Restore succeeded."
        Write-Host "Backup ID: $backupId"
        Write-Host "Safety backup: $safetyBackup"
        Write-Host "Previous storage volume retained for manual disaster recovery: $oldVolume"
    } catch {
        $originalError = $_
        if (Test-Path -LiteralPath $JournalPath) {
            try {
                Recover-InterruptedRestore
            } catch {
                throw "Restore failed and automatic rollback could not complete. Dentora remains fail-closed. Original error: $($originalError.Exception.Message)"
            }
        }
        throw $originalError
    } finally {
        if (Test-Path -LiteralPath $stage) {
            Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-DentoraMutex {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($RepoRoot.ToLowerInvariant())
        $hash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').Substring(0, 24)
    } finally {
        $sha.Dispose()
    }
    $mutex = New-Object Threading.Mutex($false, "DentoraBackupRestore_$hash")
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne(0)
    } catch [Threading.AbandonedMutexException] {
        $acquired = $true
    }
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
            if ([string]::IsNullOrWhiteSpace($ArtifactPath)) {
                throw "Restore requires the path to a Dentora backup ZIP."
            }
            Invoke-RestoreInternal -BackupPath $ArtifactPath
        }
        "recover" {
            if (-not (Test-Path -LiteralPath $JournalPath)) {
                Write-Host "No interrupted Dentora restore was found."
            } else {
                Recover-InterruptedRestore
                Write-Host "Interrupted restore was recovered safely."
            }
        }
    }
} finally {
    try { $operationMutex.ReleaseMutex() } catch { }
    $operationMutex.Dispose()
}
