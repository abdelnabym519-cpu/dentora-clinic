"""Application service for creating and validating Dentora backup artifacts."""

from __future__ import annotations

from pathlib import Path

from .domain import BackupManifest, BackupValidationError, ComponentDigest
from .infrastructure import read_json, sha256_file, validate_storage_tar, write_json_atomic

MANIFEST_FILENAME = "manifest.json"
DATABASE_FILENAME = "database.dump"
STORAGE_FILENAME = "storage.tar"
ARTIFACT_FILENAMES = frozenset({MANIFEST_FILENAME, DATABASE_FILENAME, STORAGE_FILENAME})


def create_manifest(
    root: Path,
    *,
    backup_id: str,
    created_at_utc: str,
    app_version: str,
    schema_revision: str,
) -> BackupManifest:
    root = root.resolve()
    database = root / DATABASE_FILENAME
    storage = root / STORAGE_FILENAME
    _require_regular_file(database, DATABASE_FILENAME)
    _require_regular_file(storage, STORAGE_FILENAME)
    validate_storage_tar(storage)

    manifest = BackupManifest.from_dict(
        {
            "format": "dentora-backup",
            "format_version": 1,
            "backup_id": backup_id,
            "created_at_utc": created_at_utc,
            "app_version": app_version,
            "schema_revision": schema_revision,
            "storage_backend": "local",
            "source": {
                "deployment": "dentora-client",
                "database": "postgresql",
                "storage": "local",
                "license_state": "preserved-by-installation",
            },
            "components": [
                _digest(database, DATABASE_FILENAME).to_dict(),
                _digest(storage, STORAGE_FILENAME).to_dict(),
            ],
        }
    )
    write_json_atomic(root / MANIFEST_FILENAME, manifest.to_dict())
    return validate_artifact(root, app_version=app_version, schema_revision=schema_revision)


def validate_artifact(
    root: Path,
    *,
    app_version: str,
    schema_revision: str,
) -> BackupManifest:
    root = root.resolve()
    if not root.is_dir():
        raise BackupValidationError("Backup staging directory does not exist")
    names = {entry.name for entry in root.iterdir()}
    if names != ARTIFACT_FILENAMES:
        raise BackupValidationError("Backup is incomplete or contains unexpected files")

    manifest = BackupManifest.from_dict(read_json(root / MANIFEST_FILENAME))
    manifest.assert_compatible(app_version=app_version, schema_revision=schema_revision)

    for component in manifest.components:
        path = root / component.name
        _require_regular_file(path, component.name)
        actual_size = path.stat().st_size
        if actual_size != component.size:
            raise BackupValidationError(f"Backup component {component.name} size does not match")
        actual_hash = sha256_file(path)
        if actual_hash != component.sha256:
            raise BackupValidationError(
                f"Backup component {component.name} checksum does not match"
            )

    validate_storage_tar(root / STORAGE_FILENAME)
    return manifest


def _digest(path: Path, name: str) -> ComponentDigest:
    return ComponentDigest(name=name, size=path.stat().st_size, sha256=sha256_file(path))


def _require_regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise BackupValidationError(f"Backup component {label} is missing or empty")
