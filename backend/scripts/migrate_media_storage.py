"""Non-destructive, retryable migration from local media files to S3-compatible storage.

Run from ``backend/`` after configuring S3_* environment variables. The
script never deletes source files. Re-running is safe: existing target
objects are checksum-verified instead of blindly uploaded again. Photo/X-ray
thumbnail derivatives are migrated together with their original document.
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
from app.modules.media.storage import StorageBackend
from app.modules.media.storage.configuration import S3StorageConfig
from app.modules.media.storage.local import LocalStorageBackend
from app.modules.media.storage.s3 import S3StorageBackend
from app.modules.media.thumbnails import MEDIUM_SUFFIX, THUMB_SUFFIX


@dataclass(slots=True)
class MigrationResult:
    document_id: str
    status: str


@dataclass(frozen=True, slots=True)
class SourceObject:
    path: str
    content_type: str
    size: int
    sha256: str


async def _checksum(backend: StorageBackend, path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    async for chunk in backend.iter_bytes(path):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


async def _discover_source_objects(
    document: Document,
    source: LocalStorageBackend,
) -> list[SourceObject]:
    """Discover the original plus existing thumbnail/medium binary derivatives."""
    size, checksum = await _checksum(source, document.storage_path)
    if size != document.file_size:
        raise ValueError("source_size_mismatch")

    objects = [
        SourceObject(
            path=document.storage_path,
            content_type=document.mime_type,
            size=size,
            sha256=checksum,
        )
    ]
    for suffix in (THUMB_SUFFIX, MEDIUM_SUFFIX):
        path = f"{document.storage_path}{suffix}"
        if not await source.exists(path):
            continue
        derivative_size, derivative_checksum = await _checksum(source, path)
        objects.append(
            SourceObject(
                path=path,
                content_type="image/jpeg",
                size=derivative_size,
                sha256=derivative_checksum,
            )
        )
    return objects


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
    target: StorageBackend,
    dry_run: bool,
) -> MigrationResult:
    try:
        source_objects = await _discover_source_objects(document, source)
    except FileNotFoundError:
        if not dry_run:
            await _mark_failure(document, "source_missing")
        return MigrationResult(str(document.id), "failed:source_missing")
    except ValueError as exc:
        error_code = str(exc)
        if not dry_run:
            await _mark_failure(document, error_code)
        return MigrationResult(str(document.id), f"failed:{error_code}")

    if dry_run:
        return MigrationResult(str(document.id), "dry-run")

    migrated_objects: list[dict[str, object]] = []
    try:
        for source_object in source_objects:
            duplicate = await target.exists(source_object.path)
            if not duplicate:
                await target.store_stream(
                    source.iter_bytes(source_object.path),
                    source_object.path,
                    content_type=source_object.content_type,
                    content_length=source_object.size,
                )

            target_size, target_checksum = await _checksum(target, source_object.path)
            if target_size != source_object.size or target_checksum != source_object.sha256:
                await _mark_failure(document, "checksum_mismatch")
                return MigrationResult(str(document.id), "failed:checksum_mismatch")

            migrated_objects.append(
                {
                    "object_key": source_object.path,
                    "size": source_object.size,
                    "sha256": source_object.sha256,
                    "deduplicated": duplicate,
                }
            )

        original = migrated_objects[0]
        extra = _migration_metadata(document)
        migration = dict(extra["storage_migration"])
        migration.update(
            {
                "status": "completed",
                "target_backend": "s3",
                "object_key": document.storage_path,
                "size": original["size"],
                "sha256": original["sha256"],
                "deduplicated": all(bool(item["deduplicated"]) for item in migrated_objects),
                "objects": migrated_objects,
            }
        )
        migration.pop("error_code", None)
        extra["storage_backend"] = "s3"
        extra["storage_migration"] = migration
        document.extra_data = extra
        return MigrationResult(
            str(document.id),
            "verified-existing"
            if all(bool(item["deduplicated"]) for item in migrated_objects)
            else "migrated",
        )
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
