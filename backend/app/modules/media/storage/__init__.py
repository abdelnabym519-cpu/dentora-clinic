"""Storage backend factory."""

from __future__ import annotations

import tempfile
from functools import lru_cache
from typing import Any

from app.config import settings

from .base import (
    CompletedPart,
    MultipartUpload,
    StorageBackend,
    StorageObjectInfo,
)
from .configuration import S3StorageConfig
from .local import LocalStorageBackend
from .s3 import S3StorageBackend

__all__ = [
    "CompletedPart",
    "LocalStorageBackend",
    "MultipartUpload",
    "S3StorageBackend",
    "StorageBackend",
    "StorageObjectInfo",
    "get_document_storage_backend",
    "get_storage_backend",
    "set_test_storage_path",
]

_test_storage_path: str | None = None


def set_test_storage_path(path: str | None) -> None:
    """Set storage path for tests and clear cached backend instances."""
    global _test_storage_path
    _test_storage_path = path
    _get_storage_backend.cache_clear()


def get_storage_backend(backend_name: str | None = None) -> StorageBackend:
    """Get one configured storage backend singleton by logical backend name.

    Canonicalize the logical backend name before entering the cached factory so
    implicit defaults (``None``) and explicit document hints (for example
    ``"local"``) resolve to the same backend instance.
    """
    backend = (backend_name or settings.STORAGE_BACKEND).strip().lower()
    return _get_storage_backend(backend)


@lru_cache
def _get_storage_backend(backend: str) -> StorageBackend:
    if backend == "local":
        if settings.TESTING and _test_storage_path is None:
            path = tempfile.mkdtemp(prefix="dentora_test_storage_")
            return LocalStorageBackend(path)
        path = _test_storage_path or settings.STORAGE_LOCAL_PATH
        return LocalStorageBackend(path)

    if backend == "s3":
        return S3StorageBackend(S3StorageConfig.from_env())

    raise ValueError(f"Unknown storage backend: {backend}")


# Preserve the public factory's established cache-control API while keeping
# canonicalization outside the cached implementation.
setattr(get_storage_backend, "cache_clear", _get_storage_backend.cache_clear)


def get_document_storage_backend(document: Any) -> StorageBackend:
    """Resolve a per-document migration hint or the configured default backend.

    The migration tool records ``extra_data.storage_backend=s3`` only after
    checksum verification. Rows without a hint continue to follow
    ``STORAGE_BACKEND``, preserving existing behaviour and clean cutovers.
    """
    extra_data = getattr(document, "extra_data", None) or {}
    backend = extra_data.get("storage_backend") if isinstance(extra_data, dict) else None
    return get_storage_backend(str(backend) if backend else None)
