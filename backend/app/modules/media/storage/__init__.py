"""Storage backend factory."""

from __future__ import annotations

import tempfile
from functools import lru_cache

from app.config import settings

from .base import (
    CompletedPart,
    MultipartUpload,
    StorageBackend,
    StorageCapabilityError,
    StorageObjectInfo,
    normalize_storage_key,
)
from .local import LocalStorageBackend
from .s3 import S3StorageBackend

__all__ = [
    "CompletedPart",
    "LocalStorageBackend",
    "MultipartUpload",
    "S3StorageBackend",
    "StorageBackend",
    "StorageCapabilityError",
    "StorageObjectInfo",
    "get_storage_backend",
    "normalize_storage_key",
]

_test_storage_path: str | None = None


def set_test_storage_path(path: str | None) -> None:
    """Set storage path for tests and clear the backend singleton."""

    global _test_storage_path
    _test_storage_path = path
    get_storage_backend.cache_clear()


@lru_cache
def get_storage_backend() -> StorageBackend:
    """Return the environment-selected storage adapter."""

    backend = settings.STORAGE_BACKEND.strip().lower()

    if backend == "local":
        if settings.TESTING and _test_storage_path is None:
            path = tempfile.mkdtemp(prefix="dentora_test_storage_")
            return LocalStorageBackend(path)
        path = _test_storage_path or settings.STORAGE_LOCAL_PATH
        return LocalStorageBackend(path)

    if backend == "s3":
        if not settings.S3_BUCKET.strip():
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        has_access = bool(settings.S3_ACCESS_KEY.strip())
        has_secret = bool(settings.S3_SECRET_KEY.strip())
        if has_access != has_secret:
            raise ValueError("S3_ACCESS_KEY and S3_SECRET_KEY must be configured together")
        return S3StorageBackend(
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION,
            endpoint_url=settings.S3_ENDPOINT,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            prefix=settings.S3_PREFIX,
            multipart_part_size=settings.S3_MULTIPART_PART_SIZE,
        )

    raise ValueError(f"Unknown storage backend: {settings.STORAGE_BACKEND}")
