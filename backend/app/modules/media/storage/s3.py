"""Private S3-compatible storage backend for AWS S3, MinIO and equivalents."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Sequence
from pathlib import PurePosixPath

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import (
    DEFAULT_STORAGE_CHUNK_SIZE,
    CompletedPart,
    MultipartUpload,
    StorageBackend,
    StorageObjectInfo,
)
from .configuration import S3StorageConfig

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class S3StorageBackend(StorageBackend):
    """Store all patient binary payloads as private S3 objects."""

    backend_name = "s3"
    supports_presigned_urls = True
    supports_multipart = True

    def __init__(self, config: S3StorageConfig) -> None:
        self.config = config
        client_kwargs: dict[str, object] = {
            "service_name": "s3",
            "region_name": config.region_name,
            "endpoint_url": config.endpoint_url,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": config.addressing_style},
                retries={"max_attempts": 4, "mode": "standard"},
            ),
        }
        if config.access_key is not None:
            client_kwargs["aws_access_key_id"] = config.access_key
            client_kwargs["aws_secret_access_key"] = config.secret_key
        self._client = boto3.client(**client_kwargs)

    @staticmethod
    def _validate_path(path: str) -> str:
        if not path or "\\" in path:
            raise ValueError("storage path must be a non-empty POSIX relative path")
        logical = PurePosixPath(path)
        if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
            raise ValueError("unsafe storage path")
        return logical.as_posix()

    def _key(self, path: str) -> str:
        logical = self._validate_path(path)
        if self.config.prefix:
            return f"{self.config.prefix}/{logical}"
        return logical

    async def _call(self, method_name: str, **kwargs):
        method = getattr(self._client, method_name)
        return await asyncio.to_thread(method, **kwargs)

    async def _persist_sha256_metadata(
        self,
        path: str,
        checksum: str,
        *,
        content_type: str | None,
    ) -> StorageObjectInfo:
        """Persist the full-object SHA256 after a streaming multipart upload."""
        key = self._key(path)
        kwargs: dict[str, object] = {
            "Bucket": self.config.bucket,
            "Key": key,
            "CopySource": {"Bucket": self.config.bucket, "Key": key},
            "Metadata": {"dentora-sha256": checksum},
            "MetadataDirective": "REPLACE",
        }
        if content_type:
            kwargs["ContentType"] = content_type
        await self._call("copy_object", **kwargs)
        return await self.stat(path)

    async def store(self, data: bytes, path: str) -> str:
        """Compatibility byte API routed through bounded/multipart upload logic."""

        async def _single_chunk() -> AsyncIterator[bytes]:
            if data:
                yield data

        result = await self.store_stream(
            _single_chunk(),
            path,
            content_length=len(data),
        )
        return result.path

    async def store_stream(
        self,
        chunks: AsyncIterator[bytes],
        path: str,
        *,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> StorageObjectInfo:
        """Upload incrementally, switching to multipart after the configured threshold."""
        threshold = self.config.multipart_threshold_bytes
        part_size = self.config.multipart_part_size_bytes
        buffer = bytearray()
        digest = hashlib.sha256()
        total = 0
        upload: MultipartUpload | None = None
        parts: list[CompletedPart] = []

        try:
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                digest.update(chunk)
                buffer.extend(chunk)

                if upload is None and len(buffer) >= threshold:
                    upload = await self.initiate_multipart_upload(path, content_type=content_type)

                if upload is not None:
                    while len(buffer) >= part_size:
                        payload = bytes(buffer[:part_size])
                        del buffer[:part_size]
                        parts.append(
                            await self.upload_part(
                                upload,
                                part_number=len(parts) + 1,
                                data=payload,
                            )
                        )

            if content_length is not None and total != content_length:
                raise ValueError("stream length did not match declared content_length")

            checksum = digest.hexdigest()
            if upload is None:
                kwargs: dict[str, object] = {
                    "Bucket": self.config.bucket,
                    "Key": self._key(path),
                    "Body": bytes(buffer),
                    "Metadata": {"dentora-sha256": checksum},
                }
                if content_type:
                    kwargs["ContentType"] = content_type
                response = await self._call("put_object", **kwargs)
                return StorageObjectInfo(
                    path=path,
                    size=total,
                    etag=str(response.get("ETag", "")).strip('"') or None,
                    checksum_sha256=checksum,
                )

            if buffer:
                parts.append(
                    await self.upload_part(
                        upload,
                        part_number=len(parts) + 1,
                        data=bytes(buffer),
                    )
                )
            await self.complete_multipart_upload(upload, parts)
            persisted = await self._persist_sha256_metadata(
                path,
                checksum,
                content_type=content_type,
            )
            return StorageObjectInfo(
                path=persisted.path,
                size=persisted.size,
                etag=persisted.etag,
                checksum_sha256=persisted.checksum_sha256,
            )
        except Exception:
            if upload is not None:
                try:
                    await self.abort_multipart_upload(upload)
                except Exception:
                    pass
            raise

    async def retrieve(self, path: str) -> bytes:
        key = self._key(path)

        def _read() -> bytes:
            try:
                response = self._client.get_object(Bucket=self.config.bucket, Key=key)
            except ClientError as exc:
                if str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES:
                    raise FileNotFoundError(f"File not found: {path}") from exc
                raise
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()

        return await asyncio.to_thread(_read)

    async def iter_bytes(
        self,
        path: str,
        *,
        chunk_size: int = DEFAULT_STORAGE_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        key = self._key(path)
        try:
            response = await self._call("get_object", Bucket=self.config.bucket, Key=key)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES:
                raise FileNotFoundError(f"File not found: {path}") from exc
            raise
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def delete(self, path: str) -> bool:
        if not await self.exists(path):
            return False
        await self._call("delete_object", Bucket=self.config.bucket, Key=self._key(path))
        return True

    async def exists(self, path: str) -> bool:
        try:
            await self._call("head_object", Bucket=self.config.bucket, Key=self._key(path))
            return True
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES:
                return False
            raise

    async def stat(self, path: str) -> StorageObjectInfo:
        try:
            response = await self._call(
                "head_object",
                Bucket=self.config.bucket,
                Key=self._key(path),
            )
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES:
                raise FileNotFoundError(f"File not found: {path}") from exc
            raise
        metadata = response.get("Metadata") or {}
        return StorageObjectInfo(
            path=path,
            size=int(response.get("ContentLength", 0)),
            etag=str(response.get("ETag", "")).strip('"') or None,
            checksum_sha256=metadata.get("dentora-sha256"),
        )

    async def presign_download(
        self,
        path: str,
        *,
        expires_seconds: int,
        content_disposition: str | None = None,
    ) -> str | None:
        params: dict[str, object] = {"Bucket": self.config.bucket, "Key": self._key(path)}
        if content_disposition:
            params["ResponseContentDisposition"] = content_disposition
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )

    async def presign_upload(
        self,
        path: str,
        *,
        expires_seconds: int,
        content_type: str | None = None,
    ) -> str | None:
        params: dict[str, object] = {"Bucket": self.config.bucket, "Key": self._key(path)}
        if content_type:
            params["ContentType"] = content_type
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
            HttpMethod="PUT",
        )

    async def initiate_multipart_upload(
        self,
        path: str,
        *,
        content_type: str | None = None,
    ) -> MultipartUpload:
        kwargs: dict[str, object] = {
            "Bucket": self.config.bucket,
            "Key": self._key(path),
        }
        if content_type:
            kwargs["ContentType"] = content_type
        response = await self._call("create_multipart_upload", **kwargs)
        return MultipartUpload(path=path, upload_id=str(response["UploadId"]))

    async def upload_part(
        self,
        upload: MultipartUpload,
        *,
        part_number: int,
        data: bytes,
    ) -> CompletedPart:
        if not 1 <= part_number <= 10_000:
            raise ValueError("part_number must be between 1 and 10000")
        response = await self._call(
            "upload_part",
            Bucket=self.config.bucket,
            Key=self._key(upload.path),
            UploadId=upload.upload_id,
            PartNumber=part_number,
            Body=data,
        )
        return CompletedPart(part_number=part_number, etag=str(response["ETag"]).strip('"'))

    async def complete_multipart_upload(
        self,
        upload: MultipartUpload,
        parts: Sequence[CompletedPart],
    ) -> StorageObjectInfo:
        if not parts:
            raise ValueError("multipart upload requires at least one part")
        response = await self._call(
            "complete_multipart_upload",
            Bucket=self.config.bucket,
            Key=self._key(upload.path),
            UploadId=upload.upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": part.part_number, "ETag": part.etag}
                    for part in sorted(parts, key=lambda item: item.part_number)
                ]
            },
        )
        info = await self.stat(upload.path)
        return StorageObjectInfo(
            path=upload.path,
            size=info.size,
            etag=str(response.get("ETag", "")).strip('"') or info.etag,
            checksum_sha256=info.checksum_sha256,
        )

    async def abort_multipart_upload(self, upload: MultipartUpload) -> None:
        await self._call(
            "abort_multipart_upload",
            Bucket=self.config.bucket,
            Key=self._key(upload.path),
            UploadId=upload.upload_id,
        )
