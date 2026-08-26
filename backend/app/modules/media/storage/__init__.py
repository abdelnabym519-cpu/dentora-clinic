from __future__ import annotations

import tempfile
from functools import lru_cache

from app.core.config import settings
from app.modules.scalable_architecture.domain import resilient_call

from .base import StorageBackend
from .local import LocalStorageBackend
from .s3 import S3StorageBackend

_test_storage_path: str | None = None


def storage_remote_required() -> bool:
    return settings.SCALABLE_ARCHITECTURE_MODE == "production"


def assert_storage_startup_contract() -> None:
    if storage_remote_required() and settings.MEDIA_STORAGE_BACKEND.strip().lower() != "s3":
        raise RuntimeError("production_mode_requires_s3_media_storage")


@lru_cache
def get_storage_backend(backend_name: str | None = None) -> StorageBackend:
    global _test_storage_path

    backend = (backend_name or settings.MEDIA_STORAGE_BACKEND).strip().lower()
    if storage_remote_required() and backend != "s3":
        raise RuntimeError("production_mode_requires_s3_media_storage")
    if backend == "local":
        if settings.TESTING and _test_storage_path is None:
            _test_storage_path = tempfile.mkdtemp(prefix="dentora-media-")
        storage_path = _test_storage_path or settings.MEDIA_STORAGE_PATH
        return LocalStorageBackend(storage_path)
    if backend == "s3":
        if not settings.S3_BUCKET:
            raise RuntimeError("S3_BUCKET is required when MEDIA_STORAGE_BACKEND=s3")
        return S3StorageBackend(
            bucket=settings.S3_BUCKET,
            endpoint_url=settings.S3_ENDPOINT_URL,
            region=settings.S3_REGION,
            access_key_id=settings.S3_ACCESS_KEY_ID,
            secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            use_ssl=settings.S3_USE_SSL,
            addressing_style=settings.S3_ADDRESSING_STYLE,
            signed_url_ttl_seconds=settings.MEDIA_SIGNED_URL_TTL_SECONDS,
        )
    raise RuntimeError(f"Unsupported media storage backend: {backend!r}")


def get_document_storage_backend(document) -> StorageBackend:
    return get_storage_backend(getattr(document, "storage_backend", None) or None)


async def persist_media_payload(
    backend: StorageBackend,
    storage_key: str,
    content: bytes,
    *,
    deadline_ms: int = 30_000,
) -> None:
    async def _put() -> None:
        await backend.put(storage_key, content)

    await resilient_call(
        _put,
        deadline_ms=deadline_ms,
        operation_name="media_storage.put",
        request_identity=f"media:{storage_key}",
    )


def set_test_storage_path(path: str | None) -> None:
    global _test_storage_path
    _test_storage_path = path
    get_storage_backend.cache_clear()
