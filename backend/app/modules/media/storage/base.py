"""Storage backend contracts shared by local and object-storage adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class StorageCapabilityError(RuntimeError):
    """Raised when a backend does not support an optional storage capability."""


@dataclass(frozen=True, slots=True)
class StorageObjectInfo:
    """Minimal metadata returned by storage backends without reading the payload."""

    key: str
    size: int
    etag: str | None = None
    checksum_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    """Server-owned multipart upload handle."""

    key: str
    upload_id: str


@dataclass(frozen=True, slots=True)
class CompletedPart:
    """One S3 multipart part supplied back by the authorized client."""

    part_number: int
    etag: str


def normalize_storage_key(path: str) -> str:
    """Validate and normalize a server-generated relative storage key.

    Storage keys are never accepted from an end-user request.  This guard is
    still applied at the infrastructure boundary so a compromised caller
    cannot escape the local storage root or smuggle ambiguous S3 keys.
    """

    if not path or path.startswith(('/', '\\')) or '\\' in path:
        raise ValueError("Storage key must be a non-empty relative POSIX path")

    parts = path.split('/')
    if any(part in {'', '.', '..'} for part in parts):
        raise ValueError("Storage key contains an unsafe path segment")

    normalized = str(PurePosixPath(*parts))
    if normalized != path:
        raise ValueError("Storage key is not canonical")
    return normalized


class StorageBackend(ABC):
    """Abstract storage backend for patient media.

    The original byte-oriented methods remain part of the contract for
    internal consumers and backward compatibility.  Streaming, presigned URL,
    and multipart hooks are capability methods so local development can stay
    filesystem-backed while S3 deployments avoid proxying large payloads
    through application memory.
    """

    @property
    def is_object_storage(self) -> bool:
        """Whether binary payloads are stored in an object store."""

        return False

    @property
    def supports_presigned_urls(self) -> bool:
        """Whether this backend can mint time-limited direct object URLs."""

        return False

    @property
    def supports_multipart_upload(self) -> bool:
        """Whether this backend supports server-controlled multipart uploads."""

        return False

    @abstractmethod
    async def store(self, data: bytes, path: str) -> str:
        """Store bytes at a server-generated relative key and return that key."""
        ...

    @abstractmethod
    async def retrieve(self, path: str) -> bytes:
        """Retrieve a complete object for legacy/internal consumers."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete an object, returning False when it does not exist."""
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return whether an object exists."""
        ...

    @abstractmethod
    async def stat(self, path: str) -> StorageObjectInfo:
        """Return object metadata without loading the binary payload."""
        ...

    @abstractmethod
    async def iter_chunks(self, path: str, *, chunk_size: int) -> AsyncIterator[bytes]:
        """Stream an object in bounded chunks."""
        ...

    @abstractmethod
    async def store_file(
        self,
        source_path: Path,
        path: str,
        *,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
    ) -> str:
        """Stream a local file into the backend without loading it all into RAM."""
        ...

    async def presign_download(
        self,
        path: str,
        *,
        expires_seconds: int,
        response_content_type: str | None = None,
        response_content_disposition: str | None = None,
    ) -> str:
        """Create an authorized, short-lived direct download URL."""

        raise StorageCapabilityError("Presigned downloads are not supported")

    async def presign_upload(
        self,
        path: str,
        *,
        expires_seconds: int,
        content_type: str,
        checksum_sha256: str | None = None,
    ) -> str:
        """Create an authorized, short-lived direct PUT URL."""

        raise StorageCapabilityError("Presigned uploads are not supported")

    async def create_multipart_upload(
        self,
        path: str,
        *,
        content_type: str,
        checksum_sha256: str | None = None,
    ) -> MultipartUpload:
        """Create a multipart upload for a server-selected key."""

        raise StorageCapabilityError("Multipart upload is not supported")

    async def presign_multipart_part(
        self,
        upload: MultipartUpload,
        *,
        part_number: int,
        expires_seconds: int,
    ) -> str:
        """Create a short-lived URL for one multipart part."""

        raise StorageCapabilityError("Multipart upload is not supported")

    async def complete_multipart_upload(
        self,
        upload: MultipartUpload,
        *,
        parts: list[CompletedPart],
    ) -> StorageObjectInfo:
        """Complete multipart upload and return final object metadata."""

        raise StorageCapabilityError("Multipart upload is not supported")

    async def abort_multipart_upload(self, upload: MultipartUpload) -> None:
        """Abort an incomplete multipart upload."""

        raise StorageCapabilityError("Multipart upload is not supported")
