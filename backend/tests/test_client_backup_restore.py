"""Static production contracts for the Windows Dentora Backup / Restore workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backup_wrapper_uses_single_hardened_operations_entrypoint() -> None:
    script = _read("BACKUP_DENTORA.bat")
    assert 'dentora_backup_restore.ps1" backup' in script
    assert "pg_dump" not in script
    assert "pause" in script


def test_restore_wrapper_requires_explicit_artifact_and_supports_recovery() -> None:
    script = _read("RESTORE_DENTORA.bat")
    assert "ArtifactPath" in script
    assert "--recover" in script
    assert 'dentora_backup_restore.ps1" restore' in script


def test_operations_are_admin_locked_and_concurrency_locked() -> None:
    script = _read("scripts/dentora_backup_restore.ps1")
    assert "Assert-Administrator" in script
    assert "WindowsBuiltInRole]::Administrator" in script
    assert "Threading.Mutex" in script
    assert "Another Dentora Backup / Restore operation is already running" in script


def test_backup_is_cross_component_validated_and_atomic() -> None:
    script = _read("scripts/dentora_backup_restore.ps1")
    assert '"pg_dump"' in script
    assert '"pg_restore", "--list"' in script
    assert "Get-ExpectedSchemaRevision" in script
    assert "storage.tar" in script
    assert "app.cli.backup_artifact" in script
    assert ".zip.partial" in script
    assert "Test-ZipLayout -Path $partial" in script
    assert "destination already exists; refusing to overwrite" in script


def test_backup_excludes_machine_bound_license_and_environment_secrets() -> None:
    script = _read("scripts/dentora_backup_restore.ps1")
    assert "tar --exclude='./license' --exclude='./license/*'" in script
    assert "lease.json" not in script
    assert "SECRET_KEY" not in script
    assert "POSTGRES_PASSWORD" not in script
    assert "LICENSE_MACHINE_FINGERPRINT" not in script
    assert ".env.client" not in _read("backend/app/core/backup/application.py")


def test_restore_validates_before_mutation_and_creates_safety_backup() -> None:
    script = _read("scripts/dentora_backup_restore.ps1")
    validation = script.index('"validate", "--root", "/backup"')
    safety_backup = script.index("Invoke-BackupInternal -PreRestore")
    journal = script.index("Write-RestoreJournal -Journal $journal")
    database_swap = script.index("ALTER DATABASE $dbName RENAME TO $rollbackDb")
    assert validation < safety_backup < journal < database_swap


def test_restore_uses_staged_database_and_new_storage_volume() -> None:
    script = _read("scripts/dentora_backup_restore.ps1")
    assert "dentora_restore_$nonce" in script
    assert '"--exit-on-error"' in script
    assert "Get-DatabaseSchemaRevision -Database $tempDb" in script
    assert "dentora-restore-storage-$nonce" in script
    assert '"dentora.role=restore-storage"' in script
    assert "tar -xf /backup/storage.tar -C /restore" in script
    assert "cp -a /app/storage/license/. /restore/license/" in script


def test_restore_has_journaled_rollback_and_fail_closed_health_check() -> None:
    script = _read("scripts/dentora_backup_restore.ps1")
    assert ".dentora-restore-journal.json" in script
    assert "Recover-InterruptedRestore" in script
    assert "ALTER DATABASE $rollbackDb RENAME TO $liveDb" in script
    assert 'Set-EnvValue -Name "DENTORA_STORAGE_VOLUME" -Value $oldVolume' in script
    assert "Wait-DentoraHealth" in script
    assert "Invoke-WebRequest" in script
    assert "SkipCertificateCheck" not in script
    assert "ServicePointManager" not in script


def test_start_script_refuses_ambiguous_interrupted_restore_state() -> None:
    start = _read("START_DENTORA.bat")
    assert ".dentora-restore-journal.json" in start
    assert "RESTORE_DENTORA.bat --recover" in start


def test_restore_runtime_state_and_backup_artifacts_cannot_be_committed() -> None:
    ignored = _read(".gitignore").splitlines()
    assert ".dentora-restore-journal.json" in ignored
    assert "backups/" in ignored


def test_backup_restore_documentation_keeps_next_phase_out_of_scope() -> None:
    docs = _read("BACKUP_RESTORE_AR.md")
    assert "database.dump" in docs
    assert "storage.tar" in docs
    assert "manifest.json" in docs
    assert "RESTORE_DENTORA.bat" in docs
    assert "Auto Update" in docs
    assert "خارج نطاق" in docs
