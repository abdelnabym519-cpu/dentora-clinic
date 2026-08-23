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


def test_update_preserves_machine_bound_and_data_state() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    for protected in (".env.client", "backups", ".dentora-restore-journal.json", ".git"):
        assert protected in script
    assert "docker volume rm" not in script
    assert "LICENSE_MACHINE_FINGERPRINT" not in script
    assert "POSTGRES_PASSWORD" not in script


def test_update_health_failure_rolls_back_and_start_is_fail_closed() -> None:
    script = _read("scripts/dentora_auto_update.ps1")
    start = _read("START_DENTORA.bat")
    assert "Wait-Health" in script
    assert "Recover" in script
    assert "restore -ArtifactPath" not in script  # PowerShell parameterized call, no shell command string
    assert "-Action restore -ArtifactPath" in script
    assert ".dentora-update-journal.json" in start
    assert "UPDATE_DENTORA.bat --recover" in start


def test_update_rejects_arbitrary_command_surface() -> None:
    domain = _read("backend/app/core/update/domain.py")
    assert "_ALLOWED" in domain
    assert '"command"' not in domain
    assert '"script"' not in domain


def test_update_runtime_journal_is_ignored() -> None:
    assert ".dentora-update-journal.json" in _read(".gitignore").splitlines()
