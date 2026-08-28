"""Local filesystem storage backend."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath

import aiofiles
import aiofiles.os

from .base import DEFAULT_STORAGE_CHUNK_SIZE, StorageBackend, StorageObjectInfo


class LocalStorageBackend(StorageBackend):
    """Store private binary files on a local filesystem/Docker volume."""

    backend_name = "local"

    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str) -> Path:
        """Resolve a logical object path while rejecting traversal/absolute paths."""
        if not path or "\\" in path:
            raise ValueError("storage path must be a non-empty POSIX relative path")
        logical = PurePosixPath(path)
        if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
            raise ValueError("unsafe storage path")
        candidate = self.base_path.joinpath(*logical.parts).resolve()
        if candidate != self.base_path and self.base_path not in candidate.parents:
            raise ValueError("storage path escapes the configured base directory")
        return candidate

    async def store(self, data: bytes, path: str) -> str:
        """Store file data at path."""
        full_path = self._full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(full_path, "wb") as file_obj:
            await file_obj.write(data)
        return path

    async def store_stream(
        self,
        chunks: AsyncIterator[bytes],
        path: str,
        *,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> StorageObjectInfo:
        """Write chunks incrementally and remove a partial file on failure."""
        del content_type
        full_path = self._full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            async with aiofiles.open(full_path, "wb") as file_obj:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    digest.update(chunk)
                    await file_obj.write(chunk)
        except Exception:
            if full_path.exists():
                await aiofiles.os.remove(full_path)
            raise
        if content_length is not None and size != content_length:
            if full_path.exists():
                await aiofiles.os.remove(full_path)
            raise ValueError("stream length did not match declared content_length")
        return StorageObjectInfo(path=path, size=size, checksum_sha256=digest.hexdigest())

    async def retrieve(self, path: str) -> bytes:
        """Retrieve complete file content for legacy callers."""
        full_path = self._full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        async with aiofiles.open(full_path, "rb") as file_obj:
            return await file_obj.read()

    async def iter_bytes(
        self,
        path: str,
        *,
        chunk_size: int = DEFAULT_STORAGE_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """Stream a local object without reading the complete file into RAM."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        full_path = self._full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        async with aiofiles.open(full_path, "rb") as file_obj:
            while chunk := await file_obj.read(chunk_size):
                yield chunk

    async def delete(self, path: str) -> bool:
        """Delete file from storage."""
        full_path = self._full_path(path)
        if not full_path.exists():
            return False
        await aiofiles.os.remove(full_path)
        return True

    async def exists(self, path: str) -> bool:
        """Check if file exists."""
        return self._full_path(path).is_file()

    async def stat(self, path: str) -> StorageObjectInfo:
        """Return size and a streaming SHA-256 checksum for integrity checks."""
        full_path = self._full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        digest = hashlib.sha256()
        size = 0
        async for chunk in self.iter_bytes(path):
            size += len(chunk)
            digest.update(chunk)
        return StorageObjectInfo(path=path, size=size, checksum_sha256=digest.hexdigest())
