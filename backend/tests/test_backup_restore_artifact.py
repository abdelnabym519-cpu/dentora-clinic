from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from app.core.backup import BackupValidationError, create_manifest, validate_artifact

APP_VERSION = "2.0.0"
SCHEMA_REVISION = "abc123def456"
BACKUP_ID = "dentora-20260823T120000Z-ab12cd34"
CREATED_AT = "2026-08-23T12:00:00Z"


def _write_storage_tar(path: Path, *, include_file: bool = True) -> None:
    with tarfile.open(path, "w") as archive:
        directory = tarfile.TarInfo("media")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        if include_file:
            data = b"image-bytes"
            item = tarfile.TarInfo("media/example.bin")
            item.size = len(data)
            item.mode = 0o600
            archive.addfile(item, io.BytesIO(data))


def _artifact(tmp_path: Path, *, minimal: bool = False) -> Path:
    (tmp_path / "database.dump").write_bytes(b"PGDMP\x01validated-dump")
    _write_storage_tar(tmp_path / "storage.tar", include_file=not minimal)
    create_manifest(
        tmp_path,
        backup_id=BACKUP_ID,
        created_at_utc=CREATED_AT,
        app_version=APP_VERSION,
        schema_revision=SCHEMA_REVISION,
    )
    return tmp_path


def test_create_and_validate_backup_manifest(tmp_path: Path) -> None:
    root = _artifact(tmp_path)

    manifest = validate_artifact(
        root,
        app_version=APP_VERSION,
        schema_revision=SCHEMA_REVISION,
    )

    assert manifest.backup_id == BACKUP_ID
    assert manifest.storage_backend == "local"
    assert {item.name for item in manifest.components} == {"database.dump", "storage.tar"}
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert data["format"] == "dentora-backup"
    assert data["format_version"] == 1
    assert data["source"]["license_state"] == "preserved-by-installation"
    assert not list(root.glob(".*.tmp"))


def test_empty_minimal_storage_state_is_valid(tmp_path: Path) -> None:
    root = _artifact(tmp_path, minimal=True)
    validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)


def test_repeated_validation_is_idempotent(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    first = validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)
    second = validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)
    assert first == second


def test_checksum_failure_is_fail_closed(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    (root / "database.dump").write_bytes(b"tampered")

    with pytest.raises(BackupValidationError, match="checksum"):
        validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)


def test_incomplete_backup_is_rejected(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    (root / "storage.tar").unlink()

    with pytest.raises(BackupValidationError, match="incomplete"):
        validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)


def test_corrupted_manifest_is_rejected(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    (root / "manifest.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(BackupValidationError, match="manifest"):
        validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)


def test_incompatible_application_version_is_rejected(tmp_path: Path) -> None:
    root = _artifact(tmp_path)

    with pytest.raises(BackupValidationError, match="application version"):
        validate_artifact(root, app_version="3.0.0", schema_revision=SCHEMA_REVISION)


def test_incompatible_schema_revision_is_rejected(tmp_path: Path) -> None:
    root = _artifact(tmp_path)

    with pytest.raises(BackupValidationError, match="schema"):
        validate_artifact(root, app_version=APP_VERSION, schema_revision="deadbeef")


def test_machine_bound_license_state_is_not_accepted_in_backup(tmp_path: Path) -> None:
    (tmp_path / "database.dump").write_bytes(b"PGDMP\x01validated-dump")
    with tarfile.open(tmp_path / "storage.tar", "w") as archive:
        data = b'{"lease_token":"sensitive"}'
        item = tarfile.TarInfo("license/lease.json")
        item.size = len(data)
        archive.addfile(item, io.BytesIO(data))

    with pytest.raises(BackupValidationError, match="license state"):
        create_manifest(
            tmp_path,
            backup_id=BACKUP_ID,
            created_at_utc=CREATED_AT,
            app_version=APP_VERSION,
            schema_revision=SCHEMA_REVISION,
        )


def test_storage_path_traversal_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "database.dump").write_bytes(b"PGDMP\x01validated-dump")
    with tarfile.open(tmp_path / "storage.tar", "w") as archive:
        data = b"unsafe"
        item = tarfile.TarInfo("../escape.txt")
        item.size = len(data)
        archive.addfile(item, io.BytesIO(data))

    with pytest.raises(BackupValidationError, match="traversal"):
        create_manifest(
            tmp_path,
            backup_id=BACKUP_ID,
            created_at_utc=CREATED_AT,
            app_version=APP_VERSION,
            schema_revision=SCHEMA_REVISION,
        )


def test_storage_symlinks_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "database.dump").write_bytes(b"PGDMP\x01validated-dump")
    with tarfile.open(tmp_path / "storage.tar", "w") as archive:
        link = tarfile.TarInfo("media/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)

    with pytest.raises(BackupValidationError, match="links"):
        create_manifest(
            tmp_path,
            backup_id=BACKUP_ID,
            created_at_utc=CREATED_AT,
            app_version=APP_VERSION,
            schema_revision=SCHEMA_REVISION,
        )


def test_manifest_rejects_unknown_sensitive_metadata(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    data["source"]["api_token"] = "must-never-be-here"
    (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BackupValidationError, match="source metadata"):
        validate_artifact(root, app_version=APP_VERSION, schema_revision=SCHEMA_REVISION)
