"""Production contracts for the transactional client updater and release gate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backup_and_restore_use_binary_safe_native_streams() -> None:
    script = _read("scripts/client-update.ps1")
    assert "function Invoke-DockerToFile" in script
    assert "function Invoke-DockerWithStdin" in script
    assert "Invoke-DockerToFile @('compose'" in script
    assert "Invoke-DockerWithStdin @('compose'" in script
    assert "tar','-C','/app/storage','-czf','-','.'" in script
    assert "psql','-v','ON_ERROR_STOP=1'" in script
    assert "< $dbFile" not in script


def test_recovery_is_local_only_and_uses_complete_transactions() -> None:
    script = _read("scripts/client-update.ps1")
    recover = script.index("if ($Mode -eq 'Recover')")
    network = script.index("$release = Get-Release $repository")
    assert recover < network
    assert "function Get-RecoverableTransaction" in script
    assert "database.sql" in script
    assert "storage.tar.gz" in script
    assert "env.before" in script


def test_release_manifest_is_exactly_pinned_to_official_ghcr_images() -> None:
    script = _read("scripts/client-update.ps1")
    assert "$OfficialRepository = 'abdelnabym519-cpu/dentora-clinic'" in script
    assert "Assert-ImmutableImageReference" in script
    assert 'Unauthorized release repository' in script
    assert "@sha256:" in script
    assert "Release manifest checksum verification failed." in script
    assert "Release manifest tag does not match the GitHub Release." in script


def test_release_workflow_gates_publish_and_emits_portable_checksum() -> None:
    workflow = _read(".github/workflows/release.yml")
    assert "quality:" in workflow
    assert "uses: ./.github/workflows/ci.yml" in workflow
    assert "update-security:" in workflow
    assert "needs: [quality, update-security, release-meta]" in workflow
    assert "branches: [\"release/v*\"]" in workflow
    assert "sha256sum dentora-release-manifest.json > dentora-release-manifest.json.sha256" in workflow
    assert "sha256sum release-assets/dentora-release-manifest.json" not in workflow
    assert "--target \"$GITHUB_SHA\"" in workflow


def test_release_runs_real_update_rollback_and_recovery_validation() -> None:
    workflow = _read(".github/workflows/release.yml")
    assert "client-validation:" in workflow
    assert "scripts/client-update.ps1 -Mode Check" in workflow
    assert "scripts/client-update.ps1 -Mode Update" in workflow
    for point in ("after-backup", "after-install", "after-health"):
        assert point in workflow
    assert "kill -9 \"$updater_pid\"" in workflow
    assert "scripts/client-update.ps1 -Mode Recover" in workflow
    assert "auto-update-production-validation" in workflow
