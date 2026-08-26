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
    get_storage_backend.cache_clear()


@lru_cache
def get_storage_backend(backend_name: str | None = None) -> StorageBackend:
    """Get one configured storage backend singleton by logical backend name."""
    global _test_storage_path

    backend = (backend_name or settings.STORAGE_BACKEND).strip().lower()

    if backend == "local":
        if settings.TESTING and _test_storage_path is None:
            _test_storage_path = tempfile.mkdtemp(prefix="dentora_test_storage_")
        path = _test_storage_path or settings.STORAGE_LOCAL_PATH
        return LocalStorageBackend(path)

    if backend == "s3":
        return S3StorageBackend(S3StorageConfig.from_env())

    raise ValueError(f"Unknown storage backend: {backend}")


def get_document_storage_backend(document: Any) -> StorageBackend:
    """Resolve the backend recorded on a document, preserving legacy local rows.

    Existing rows predate backend hints and therefore represent files in
    ``/app/storage``. New rows record the backend in ``extra_data`` so a
    non-destructive local-to-object migration can be gradual and retryable.
    """
    extra_data = getattr(document, "extra_data", None) or {}
    backend = extra_data.get("storage_backend") if isinstance(extra_data, dict) else None
    return get_storage_backend(str(backend) if backend else "local")
