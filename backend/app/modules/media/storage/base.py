"""Abstract storage contracts shared by local and object-storage adapters."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

DEFAULT_STORAGE_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class StorageObjectInfo:
    """Backend-neutral metadata for one stored object."""

    path: str
    size: int
    etag: str | None = None
    checksum_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    """Opaque multipart-upload handle returned by a storage backend."""

    path: str
    upload_id: str


@dataclass(frozen=True, slots=True)
class CompletedPart:
    """One uploaded multipart part."""

    part_number: int
    etag: str


class StorageBackend(ABC):
    """Abstract storage backend for private patient binary objects.

    ``store``/``retrieve`` remain the compatibility surface used by older
    call sites. New code should prefer ``store_stream``/``iter_bytes`` so
    large objects do not have to be materialised fully in application RAM.
    """

    backend_name = "unknown"
    supports_presigned_urls = False
    supports_multipart = False

    @abstractmethod
    async def store(self, data: bytes, path: str) -> str:
        """Store file data at a logical storage path and return that path."""
        ...

    @abstractmethod
    async def retrieve(self, path: str) -> bytes:
        """Retrieve the complete object for backwards-compatible callers."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete an object, returning whether an object existed."""
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return whether the logical path exists."""
        ...

    async def store_stream(
        self,
        chunks: AsyncIterator[bytes],
        path: str,
        *,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> StorageObjectInfo:
        """Compatibility streaming fallback for third-party backends.

        First-party local and S3 adapters override this with bounded-memory
        implementations. Keeping a default prevents the interface extension
        from breaking an out-of-tree backend that only implements the legacy
        byte API.
        """
        del content_type, content_length
        data = bytearray()
        async for chunk in chunks:
            if chunk:
                data.extend(chunk)
        payload = bytes(data)
        stored_path = await self.store(payload, path)
        return StorageObjectInfo(
            path=stored_path,
            size=len(payload),
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
        )

    async def iter_bytes(
        self,
        path: str,
        *,
        chunk_size: int = DEFAULT_STORAGE_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """Compatibility streaming reader; first-party backends override it."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        data = await self.retrieve(path)
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    async def stat(self, path: str) -> StorageObjectInfo:
        """Return size/checksum metadata using the compatibility byte API."""
        data = await self.retrieve(path)
        return StorageObjectInfo(
            path=path,
            size=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )

    async def presign_download(
        self,
        path: str,
        *,
        expires_seconds: int,
        content_disposition: str | None = None,
    ) -> str | None:
        """Return a private temporary GET URL when the backend supports it."""
        del path, expires_seconds, content_disposition
        return None

    async def presign_upload(
        self,
        path: str,
        *,
        expires_seconds: int,
        content_type: str | None = None,
    ) -> str | None:
        """Return a private temporary PUT URL when the backend supports it."""
        del path, expires_seconds, content_type
        return None

    async def initiate_multipart_upload(
        self,
        path: str,
        *,
        content_type: str | None = None,
    ) -> MultipartUpload:
        """Create a multipart upload when supported by the backend."""
        del path, content_type
        raise NotImplementedError(f"{type(self).__name__} does not support multipart uploads")

    async def upload_part(
        self,
        upload: MultipartUpload,
        *,
        part_number: int,
        data: bytes,
    ) -> CompletedPart:
        """Upload one multipart part."""
        del upload, part_number, data
        raise NotImplementedError(f"{type(self).__name__} does not support multipart uploads")

    async def complete_multipart_upload(
        self,
        upload: MultipartUpload,
        parts: Sequence[CompletedPart],
    ) -> StorageObjectInfo:
        """Complete a multipart upload."""
        del upload, parts
        raise NotImplementedError(f"{type(self).__name__} does not support multipart uploads")

    async def abort_multipart_upload(self, upload: MultipartUpload) -> None:
        """Abort a multipart upload without exposing backend credentials."""
        del upload
        raise NotImplementedError(f"{type(self).__name__} does not support multipart uploads")
