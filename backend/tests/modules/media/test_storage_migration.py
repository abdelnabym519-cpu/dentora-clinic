"""Integrity and retry contracts for local-to-object media migration."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import ClinicMembership
from app.modules.media.models import Document
from app.modules.media.storage import LocalStorageBackend, StorageBackend, normalize_storage_key
from app.modules.media.storage.migrate import MediaStorageMigrator
from app.modules.patients.models import Patient


class _MemoryObjectStorage(StorageBackend):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.store_file_calls = 0

    @property
    def is_object_storage(self) -> bool:
        return True

    async def store(self, data: bytes, path: str) -> str:
        key = normalize_storage_key(path)
        self.objects[key] = data
        return key

    async def retrieve(self, path: str) -> bytes:
        key = normalize_storage_key(path)
        try:
            return self.objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    async def delete(self, path: str) -> bool:
        return self.objects.pop(normalize_storage_key(path), None) is not None

    async def exists(self, path: str) -> bool:
        return normalize_storage_key(path) in self.objects

    async def store_file(
        self,
        source_path: Path,
        path: str,
        *,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
    ) -> str:
        del content_type
        self.store_file_calls += 1
        payload = source_path.read_bytes()
        if checksum_sha256 is not None:
            assert hashlib.sha256(payload).hexdigest() == checksum_sha256.lower()
        return await self.store(payload, path)


class _CorruptObjectStorage(_MemoryObjectStorage):
    async def store_file(
        self,
        source_path: Path,
        path: str,
        *,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
    ) -> str:
        del source_path, content_type, checksum_sha256
        self.store_file_calls += 1
        return await self.store(b"corrupted-after-copy", path)


async def _document(
    db_session: AsyncSession,
    patient: Patient,
    *,
    key: str,
    payload: bytes,
) -> Document:
    uploader_id = (
        await db_session.execute(
            select(ClinicMembership.user_id).where(
                ClinicMembership.clinic_id == patient.clinic_id,
                ClinicMembership.role == "admin",
            )
        )
    ).scalar_one()
    document = Document(
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        document_type="other",
        title="Storage migration fixture",
        description=None,
        original_filename="migration.bin",
        storage_path=key,
        mime_type="application/octet-stream",
        file_size=len(payload),
        media_kind="document",
        media_category=None,
        media_subtype=None,
        captured_at=None,
        paired_document_id=None,
        tags=[],
        extra_data={},
        uploaded_by=uploader_id,
        status="active",
    )
    db_session.add(document)
    await db_session.commit()
    return document


@pytest.mark.asyncio
async def test_migration_verifies_integrity_is_idempotent_and_retains_local_source(
    db_session: AsyncSession,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    source = LocalStorageBackend(str(tmp_path / "local-media"))
    target = _MemoryObjectStorage()
    key = f"{test_patient.clinic_id}/{test_patient.id}/migration.bin"
    payload = b"dentora-scalable-media-migration"
    checksum = hashlib.sha256(payload).hexdigest()
    await source.store(payload, key)
    document = await _document(db_session, test_patient, key=key, payload=payload)

    first = await MediaStorageMigrator(db_session, source=source, target=target).run(
        document_id=document.id
    )
    assert first.discovered == 1
    assert first.migrated == 1
    assert first.failed == 0
    assert target.objects[key] == payload
    assert await source.retrieve(key) == payload

    await db_session.refresh(document)
    migration = document.extra_data["storage_migration"]
    assert migration["state"] == "verified"
    assert migration["storage_reference"] == key
    assert migration["local_source_retained"] is True
    assert migration["objects"][key] == {"size": len(payload), "sha256": checksum}

    second = await MediaStorageMigrator(db_session, source=source, target=target).run(
        document_id=document.id
    )
    assert second.already_verified == 1
    assert second.failed == 0
    assert target.store_file_calls == 1
    assert await source.retrieve(key) == payload


@pytest.mark.asyncio
async def test_migration_rejects_corruption_and_keeps_local_source(
    db_session: AsyncSession,
    test_patient: Patient,
    tmp_path: Path,
) -> None:
    source = LocalStorageBackend(str(tmp_path / "local-media"))
    target = _CorruptObjectStorage()
    key = f"{test_patient.clinic_id}/{test_patient.id}/corruption.bin"
    payload = b"must-survive-a-bad-object-copy"
    await source.store(payload, key)
    document = await _document(db_session, test_patient, key=key, payload=payload)

    result = await MediaStorageMigrator(
        db_session,
        source=source,
        target=target,
        retries=1,
    ).run(document_id=document.id)
    assert result.discovered == 1
    assert result.migrated == 0
    assert result.failed == 1
    assert await source.retrieve(key) == payload

    await db_session.refresh(document)
    migration = document.extra_data["storage_migration"]
    assert migration["state"] == "failed"
    assert migration["local_source_retained"] is True
    assert "Integrity verification failed" in migration["error"]
