"""Non-destructive, retryable migration from local media files to S3-compatible storage.

Run from ``backend/`` after configuring S3_* environment variables. The
script never deletes the source file. Re-running is safe: an existing target
object is checksum-verified instead of uploaded again.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from dataclasses import dataclass

from sqlalchemy import select

from app.config import settings
from app.database import async_session_maker
from app.modules.media.models import Document
from app.modules.media.storage.configuration import S3StorageConfig
from app.modules.media.storage.local import LocalStorageBackend
from app.modules.media.storage.s3 import S3StorageBackend


@dataclass(slots=True)
class MigrationResult:
    document_id: str
    status: str


async def _checksum(backend, path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    async for chunk in backend.iter_bytes(path):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _migration_metadata(document: Document) -> dict:
    extra = dict(document.extra_data or {})
    migration = dict(extra.get("storage_migration") or {})
    migration["attempts"] = int(migration.get("attempts", 0)) + 1
    extra["storage_migration"] = migration
    return extra


async def _mark_failure(document: Document, error_code: str) -> None:
    extra = _migration_metadata(document)
    migration = dict(extra["storage_migration"])
    migration.update(
        {
            "status": "failed",
            "target_backend": "s3",
            "object_key": document.storage_path,
            "error_code": error_code,
        }
    )
    extra["storage_migration"] = migration
    document.extra_data = extra


async def migrate_document(
    document: Document,
    *,
    source: LocalStorageBackend,
    target: S3StorageBackend,
    dry_run: bool,
) -> MigrationResult:
    path = document.storage_path
    try:
        source_size, source_checksum = await _checksum(source, path)
    except FileNotFoundError:
        if not dry_run:
            await _mark_failure(document, "source_missing")
        return MigrationResult(str(document.id), "failed:source_missing")

    if source_size != document.file_size:
        if not dry_run:
            await _mark_failure(document, "source_size_mismatch")
        return MigrationResult(str(document.id), "failed:source_size_mismatch")

    if dry_run:
        return MigrationResult(str(document.id), "dry-run")

    try:
        duplicate = await target.exists(path)
        if not duplicate:
            await target.store_stream(
                source.iter_bytes(path),
                path,
                content_type=document.mime_type,
                content_length=source_size,
            )

        target_size, target_checksum = await _checksum(target, path)
        if target_size != source_size or target_checksum != source_checksum:
            await _mark_failure(document, "checksum_mismatch")
            return MigrationResult(str(document.id), "failed:checksum_mismatch")

        extra = _migration_metadata(document)
        migration = dict(extra["storage_migration"])
        migration.update(
            {
                "status": "completed",
                "target_backend": "s3",
                "object_key": path,
                "size": source_size,
                "sha256": source_checksum,
                "deduplicated": duplicate,
            }
        )
        migration.pop("error_code", None)
        extra["storage_backend"] = "s3"
        extra["storage_migration"] = migration
        document.extra_data = extra
        return MigrationResult(str(document.id), "verified-existing" if duplicate else "migrated")
    except Exception as exc:
        await _mark_failure(document, type(exc).__name__)
        return MigrationResult(str(document.id), f"failed:{type(exc).__name__}")


async def run(*, dry_run: bool, limit: int | None) -> int:
    source = LocalStorageBackend(settings.STORAGE_LOCAL_PATH)
    target = S3StorageBackend(S3StorageConfig.from_env())

    migrated = 0
    failed = 0
    skipped = 0
    async with async_session_maker() as db:
        statement = select(Document).order_by(Document.created_at.asc(), Document.id.asc())
        if limit is not None:
            statement = statement.limit(limit)
        documents = list((await db.execute(statement)).scalars().all())

        for document in documents:
            migration = (document.extra_data or {}).get("storage_migration") or {}
            if migration.get("status") == "completed" and migration.get("target_backend") == "s3":
                skipped += 1
                print(f"{document.id} skipped:already-completed")
                continue

            result = await migrate_document(
                document,
                source=source,
                target=target,
                dry_run=dry_run,
            )
            print(f"{result.document_id} {result.status}")
            if result.status.startswith("failed"):
                failed += 1
            elif result.status != "dry-run":
                migrated += 1

            if not dry_run:
                await db.commit()

    print(f"summary migrated={migrated} failed={failed} skipped={skipped} dry_run={dry_run}")
    return 1 if failed else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="discover and validate only")
    parser.add_argument("--limit", type=int, default=None, help="optional maximum rows for one run")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    raise SystemExit(asyncio.run(run(dry_run=args.dry_run, limit=args.limit)))


if __name__ == "__main__":
    main()
