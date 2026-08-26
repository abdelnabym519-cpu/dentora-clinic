"""Non-destructive local-filesystem to S3 media migration.

Run before switching ``STORAGE_BACKEND`` to ``s3``.  The database's
``storage_path`` is a backend-neutral logical object key, so a successful
migration keeps that key stable and records verification metadata only after
all existing binary variants have been copied and SHA-256 verified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_maker
from app.modules.media.models import Document
from app.modules.media.thumbnails import MEDIUM_SUFFIX, THUMB_SUFFIX, is_thumbnailable

from .base import StorageBackend
from .local import LocalStorageBackend
from .s3 import S3StorageBackend


@dataclass(slots=True)
class MigrationResult:
    discovered: int = 0
    migrated: int = 0
    already_verified: int = 0
    dry_run: int = 0
    failed: int = 0


async def _sha256(storage: StorageBackend, key: str) -> str:
    digest = hashlib.sha256()
    async for chunk in storage.iter_chunks(key, chunk_size=settings.STORAGE_STREAM_CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


class MediaStorageMigrator:
    """Retryable, integrity-verified copier that never deletes local media."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        source: LocalStorageBackend,
        target: StorageBackend,
        retries: int = 3,
    ) -> None:
        if not target.is_object_storage:
            raise ValueError("Migration target must be object storage")
        self.db = db
        self.source = source
        self.target = target
        self.retries = max(1, retries)

    async def run(
        self,
        *,
        dry_run: bool = False,
        document_id: UUID | None = None,
        limit: int | None = None,
    ) -> MigrationResult:
        query = select(Document).order_by(Document.created_at.asc(), Document.id.asc())
        if document_id is not None:
            query = query.where(Document.id == document_id)
        if limit is not None:
            query = query.limit(max(1, limit))
        documents = list((await self.db.execute(query)).scalars().all())
        result = MigrationResult(discovered=len(documents))

        for document in documents:
            current_document_id = document.id
            try:
                if dry_run:
                    await self._validate_source_set(document)
                    result.dry_run += 1
                    continue
                copied = await self._migrate_document(document)
                if copied:
                    result.migrated += 1
                else:
                    result.already_verified += 1
                await self.db.commit()
            except Exception as exc:
                await self.db.rollback()
                result.failed += 1
                if not dry_run:
                    await self._record_failure(current_document_id, str(exc))
        return result

    async def _variant_keys(self, document: Document) -> list[tuple[str, str | None]]:
        variants: list[tuple[str, str | None]] = [(document.storage_path, document.mime_type)]
        if is_thumbnailable(document.mime_type):
            for suffix in (THUMB_SUFFIX, MEDIUM_SUFFIX):
                key = f"{document.storage_path}{suffix}"
                if await self.source.exists(key):
                    variants.append((key, "image/jpeg"))
        return variants

    async def _validate_source_set(self, document: Document) -> None:
        if not await self.source.exists(document.storage_path):
            raise FileNotFoundError(f"Local source is missing for document {document.id}")
        async for _ in self.source.iter_chunks(
            document.storage_path, chunk_size=settings.STORAGE_STREAM_CHUNK_SIZE
        ):
            pass

    async def _migrate_document(self, document: Document) -> bool:
        if not await self.source.exists(document.storage_path):
            raise FileNotFoundError(f"Local source is missing for document {document.id}")

        copied_any = False
        verified: dict[str, dict[str, int | str]] = {}
        for key, content_type in await self._variant_keys(document):
            source_info = await self.source.stat(key)
            source_sha = await _sha256(self.source, key)
            already_same = False
            if await self.target.exists(key):
                target_info = await self.target.stat(key)
                if target_info.size == source_info.size:
                    target_sha = await _sha256(self.target, key)
                    already_same = target_sha == source_sha
            if not already_same:
                await self._copy_with_retry(
                    key,
                    content_type=content_type,
                    checksum_sha256=source_sha,
                )
                copied_any = True

            final_info = await self.target.stat(key)
            final_sha = await _sha256(self.target, key)
            if final_info.size != source_info.size or final_sha != source_sha:
                raise ValueError(f"Integrity verification failed for {key}")
            verified[key] = {"size": final_info.size, "sha256": final_sha}

        envelope = dict(document.extra_data or {})
        envelope["storage_migration"] = {
            "state": "verified",
            "source": "local",
            "target": "s3",
            "storage_reference": document.storage_path,
            "objects": verified,
            "local_source_retained": True,
        }
        document.extra_data = envelope
        await self.db.flush()
        return copied_any

    async def _copy_with_retry(
        self,
        key: str,
        *,
        content_type: str | None,
        checksum_sha256: str,
    ) -> None:
        last_error: Exception | None = None
        for _attempt in range(1, self.retries + 1):
            try:
                await self.target.store_file(
                    self.source.filesystem_path(key),
                    key,
                    content_type=content_type,
                    checksum_sha256=checksum_sha256,
                )
                return
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def _record_failure(self, document_id: UUID, error: str) -> None:
        document = (
            await self.db.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
        if document is None:
            return
        envelope = dict(document.extra_data or {})
        envelope["storage_migration"] = {
            "state": "failed",
            "source": "local",
            "target": "s3",
            "error": error[:1000],
            "local_source_retained": True,
        }
        document.extra_data = envelope
        await self.db.commit()


def _target() -> S3StorageBackend:
    return S3StorageBackend(
        bucket=settings.S3_BUCKET,
        region=settings.S3_REGION,
        endpoint_url=settings.S3_ENDPOINT,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        prefix=settings.S3_PREFIX,
        multipart_part_size=settings.S3_MULTIPART_PART_SIZE,
    )


async def _main(args: argparse.Namespace) -> int:
    source = LocalStorageBackend(settings.STORAGE_LOCAL_PATH)
    target = _target()
    async with async_session_maker() as db:
        result = await MediaStorageMigrator(
            db, source=source, target=target, retries=args.retries
        ).run(
            dry_run=args.dry_run,
            document_id=UUID(args.document_id) if args.document_id else None,
            limit=args.limit,
        )
    print(
        "media-storage-migration "
        f"discovered={result.discovered} migrated={result.migrated} "
        f"already_verified={result.already_verified} dry_run={result.dry_run} "
        f"failed={result.failed}"
    )
    return 1 if result.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Dentora local media to S3")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--document-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retries", type=int, default=3)
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
