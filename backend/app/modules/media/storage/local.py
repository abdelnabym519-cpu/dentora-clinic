"""Local filesystem storage backend."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import aiofiles.os

from .base import StorageBackend, StorageObjectInfo, normalize_storage_key


class LocalStorageBackend(StorageBackend):
    """Store files on a private local filesystem (normally a Docker volume)."""

    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str) -> Path:
        key = normalize_storage_key(path)
        candidate = (self.base_path / key).resolve()
        if candidate != self.base_path and self.base_path not in candidate.parents:
            raise ValueError("Storage key escapes configured storage root")
        return candidate

    def filesystem_path(self, path: str) -> Path:
        """Return a traversal-safe source path for migration tooling."""

        return self._full_path(path)

    async def store(self, data: bytes, path: str) -> str:
        key = normalize_storage_key(path)
        full_path = self._full_path(key)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(full_path, "wb") as file_obj:
            await file_obj.write(data)
        return key

    async def retrieve(self, path: str) -> bytes:
        full_path = self._full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        async with aiofiles.open(full_path, "rb") as file_obj:
            return await file_obj.read()

    async def delete(self, path: str) -> bool:
        full_path = self._full_path(path)
        if not full_path.exists():
            return False
        await aiofiles.os.remove(full_path)
        return True

    async def exists(self, path: str) -> bool:
        return self._full_path(path).is_file()

    async def stat(self, path: str) -> StorageObjectInfo:
        key = normalize_storage_key(path)
        full_path = self._full_path(key)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        stats = await aiofiles.os.stat(full_path)
        return StorageObjectInfo(key=key, size=stats.st_size)

    async def iter_chunks(self, path: str, *, chunk_size: int) -> AsyncIterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        full_path = self._full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        async with aiofiles.open(full_path, "rb") as file_obj:
            while True:
                chunk = await file_obj.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def store_file(
        self,
        source_path: Path,
        path: str,
        *,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
    ) -> str:
        del content_type
        key = normalize_storage_key(path)
        destination = self._full_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        async with aiofiles.open(source_path, "rb") as source, aiofiles.open(
            destination, "wb"
        ) as target:
            while True:
                chunk = await source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                await target.write(chunk)
        if checksum_sha256 is not None and digest.hexdigest() != checksum_sha256.lower():
            await aiofiles.os.remove(destination)
            raise ValueError("Source checksum does not match expected SHA-256")
        return key
