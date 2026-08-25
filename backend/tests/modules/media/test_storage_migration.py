from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.media.storage.local import LocalStorageBackend
from app.modules.media.thumbnails import MEDIUM_SUFFIX, THUMB_SUFFIX
from scripts.migrate_media_storage import migrate_document


@pytest.fixture
def document():
    return SimpleNamespace(
        id=uuid4(),
        storage_path="clinic/patient/2026-08/file.bin",
        mime_type="application/octet-stream",
        file_size=6,
        extra_data={},
    )


@pytest.mark.asyncio
async def test_migration_success_is_non_destructive_and_verified(tmp_path, document) -> None:
    source = LocalStorageBackend(str(tmp_path / "source"))
    target = LocalStorageBackend(str(tmp_path / "target"))
    await source.store(b"abcdef", document.storage_path)

    result = await migrate_document(document, source=source, target=target, dry_run=False)

    assert result.status == "migrated"
    assert await source.retrieve(document.storage_path) == b"abcdef"
    assert await target.retrieve(document.storage_path) == b"abcdef"
    assert document.extra_data["storage_backend"] == "s3"
    assert document.extra_data["storage_migration"]["status"] == "completed"
    assert document.extra_data["storage_migration"]["sha256"]


@pytest.mark.asyncio
async def test_migration_moves_existing_image_derivatives_without_deleting_source(
    tmp_path, document
) -> None:
    source = LocalStorageBackend(str(tmp_path / "source"))
    target = LocalStorageBackend(str(tmp_path / "target"))
    await source.store(b"abcdef", document.storage_path)
    await source.store(b"thumb", f"{document.storage_path}{THUMB_SUFFIX}")
    await source.store(b"medium", f"{document.storage_path}{MEDIUM_SUFFIX}")

    result = await migrate_document(document, source=source, target=target, dry_run=False)

    assert result.status == "migrated"
    for suffix, expected in ((THUMB_SUFFIX, b"thumb"), (MEDIUM_SUFFIX, b"medium")):
        path = f"{document.storage_path}{suffix}"
        assert await source.retrieve(path) == expected
        assert await target.retrieve(path) == expected
    objects = document.extra_data["storage_migration"]["objects"]
    assert {item["object_key"] for item in objects} == {
        document.storage_path,
        f"{document.storage_path}{THUMB_SUFFIX}",
        f"{document.storage_path}{MEDIUM_SUFFIX}",
    }


@pytest.mark.asyncio
async def test_migration_existing_identical_target_avoids_duplicate_upload(tmp_path, document) -> None:
    source = LocalStorageBackend(str(tmp_path / "source"))
    target = LocalStorageBackend(str(tmp_path / "target"))
    await source.store(b"abcdef", document.storage_path)
    await target.store(b"abcdef", document.storage_path)

    result = await migrate_document(document, source=source, target=target, dry_run=False)

    assert result.status == "verified-existing"
    assert document.extra_data["storage_migration"]["deduplicated"] is True


@pytest.mark.asyncio
async def test_migration_checksum_mismatch_records_failure_and_retry_succeeds(tmp_path, document) -> None:
    source = LocalStorageBackend(str(tmp_path / "source"))
    target = LocalStorageBackend(str(tmp_path / "target"))
    await source.store(b"abcdef", document.storage_path)
    await target.store(b"xxxxxx", document.storage_path)

    failed = await migrate_document(document, source=source, target=target, dry_run=False)
    assert failed.status == "failed:checksum_mismatch"
    assert document.extra_data["storage_migration"]["status"] == "failed"

    await target.delete(document.storage_path)
    retried = await migrate_document(document, source=source, target=target, dry_run=False)
    assert retried.status == "migrated"
    assert document.extra_data["storage_migration"]["status"] == "completed"
    assert document.extra_data["storage_migration"]["attempts"] == 2


@pytest.mark.asyncio
async def test_migration_missing_source_records_failure(tmp_path, document) -> None:
    source = LocalStorageBackend(str(tmp_path / "source"))
    target = LocalStorageBackend(str(tmp_path / "target"))

    result = await migrate_document(document, source=source, target=target, dry_run=False)

    assert result.status == "failed:source_missing"
    assert document.extra_data["storage_migration"]["error_code"] == "source_missing"


@pytest.mark.asyncio
async def test_migration_dry_run_writes_nothing(tmp_path, document) -> None:
    source = LocalStorageBackend(str(tmp_path / "source"))
    target = LocalStorageBackend(str(tmp_path / "target"))
    await source.store(b"abcdef", document.storage_path)

    result = await migrate_document(document, source=source, target=target, dry_run=True)

    assert result.status == "dry-run"
    assert await target.exists(document.storage_path) is False
    assert document.extra_data == {}
