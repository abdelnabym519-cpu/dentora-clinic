"""Static production contracts for Dentora Auto Update."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_update_wrapper_exposes_check_apply_and_recovery() -> None:
    wrapper = _read("UPDATE_DENTORA.bat")
    assert "--check" in wrapper
    assert "--recover" in wrapper
    assert "dentora_auto_update.ps1" in wrapper


def test_update_requires_dedicated_https_metadata_and_signing_key() -> None:
    env = _read(".env.client.example")
    script = _read("scripts/dentora_auto_update.ps1")
    assert "UPDATE_METADATA_URL=" in env
    assert "UPDATE_PUBLIC_KEY_B64=" in env
    assert "UPDATE_METADATA_URL must use HTTPS" in script
    assert "app.cli.update_artifact" in script
    assert "--public-key-b64" in script


def test_update_reuses_backup_restore_and_journals_before_mutation() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    assert "dentora_backup_restore.ps1" in script
    assert "Mandatory pre-update backup failed" in script
    assert ".dentora-update-journal.json" in script
    assert script.index("$backup = New-Backup") < script.index('phase="prepared"')
    assert script.index('phase="prepared"') < script.index("Copy-Item (Join-Path $stage '*')")


def test_backup_failure_cannot_enter_mutating_phase() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    backup = script.index("$backup = New-Backup")
    journal = script.index('phase="prepared"')
    mutation = script.index("Copy-Item (Join-Path $stage '*')")
    assert backup < journal < mutation
    assert 'throw "Mandatory pre-update backup failed."' in script


def test_update_preserves_machine_bound_configuration_and_data_state() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    for protected in (".env.client", "backups", ".dentora-restore-journal.json", ".git"):
        assert protected in script
    assert "docker volume rm" not in script
    assert "LICENSE_MACHINE_FINGERPRINT" not in script
    assert "POSTGRES_PASSWORD" not in script


def test_update_uses_exclusive_concurrency_lock() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    assert 'Threading.Mutex($false, "DentoraAutoUpdate")' in script
    assert ".WaitOne(0)" in script
    assert "Another Dentora Auto Update operation is already running." in script
    assert ".ReleaseMutex()" in script


def test_interrupted_update_is_fail_closed_and_recoverable() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    start = _read("START_DENTORA.bat")
    assert 'if (Test-Path $Journal) { throw "Recover the interrupted update first." }' in script
    assert ".dentora-update-journal.json" in start
    assert "UPDATE_DENTORA.bat --recover" in start
    assert "Rollback snapshot is missing. Dentora remains fail-closed." in script


def test_update_has_observable_transaction_lifecycle() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    assert 'phase="prepared"' in script
    assert '$state.phase="files_applied"' in script
    assert '$state.phase="services_started"' in script
    assert "Dentora update succeeded:" in script


def test_migrations_run_via_normal_backend_entrypoint_and_failure_rolls_back() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    entrypoint = _read("backend/docker-entrypoint.sh")
    assert "alembic upgrade heads" in entrypoint
    assert "function Invoke-Compose([string[]]$Arguments)" in script
    assert "@Arguments" in script
    assert 'Invoke-Compose @("up", "-d", "--build", "db", "backend", "frontend", "caddy")' in script
    assert "catch { $original=$_; try { Recover }" in script
    assert "-Action restore -ArtifactPath" in script


def test_update_health_failure_rolls_back_and_start_is_fail_closed() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    start = _read("START_DENTORA.bat")
    assert "Wait-Health" in script
    assert "Recover" in script
    assert "-Action restore -ArtifactPath" in script
    assert ".dentora-update-journal.json" in start
    assert "UPDATE_DENTORA.bat --recover" in start


def test_success_clears_journal_only_after_health_and_version_validation() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    health = script.index("        Wait-Health")
    version = script.index("        if ((Get-Version) -ne [string]$u.Descriptor.version)")
    clear = script.index("        Remove-Item $Journal -Force")
    assert health < version < clear


def test_recovery_is_idempotent_when_no_interruption_exists() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    assert (
        'if (-not (Test-Path $Journal)) { Write-Host "No interrupted update was found."; return }'
        in script
    )


def test_update_rejects_arbitrary_command_surface() -> None:
    domain = _read("backend/app/core/update/domain.py")
    assert "_ALLOWED" in domain
    assert '"command"' not in domain
    assert '"script"' not in domain


def test_update_runtime_journal_is_ignored() -> None:
    assert ".dentora-update-journal.json" in _read(".gitignore").splitlines()
