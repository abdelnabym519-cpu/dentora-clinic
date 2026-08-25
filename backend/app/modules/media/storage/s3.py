"""S3-compatible private object-storage backend."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import (
    CompletedPart,
    MultipartUpload,
    StorageBackend,
    StorageObjectInfo,
    normalize_storage_key,
)


class S3StorageBackend(StorageBackend):
    """Private S3/MinIO adapter implementing Dentora's storage contract."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "",
        endpoint_url: str = "",
        access_key: str = "",
        secret_key: str = "",
        prefix: str = "",
        multipart_part_size: int = 8 * 1024 * 1024,
        client: Any | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        if multipart_part_size < 5 * 1024 * 1024:
            raise ValueError("S3 multipart part size must be at least 5 MiB")

        self.bucket = bucket.strip()
        self.prefix = self._normalize_prefix(prefix)
        self.multipart_part_size = multipart_part_size
        if client is not None:
            self.client = client
        else:
            kwargs: dict[str, Any] = {
                "service_name": "s3",
                "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            }
            if endpoint_url.strip():
                kwargs["endpoint_url"] = endpoint_url.strip()
            if region.strip():
                kwargs["region_name"] = region.strip()
            if access_key.strip():
                kwargs["aws_access_key_id"] = access_key.strip()
            if secret_key.strip():
                kwargs["aws_secret_access_key"] = secret_key.strip()
            self.client = boto3.client(**kwargs)

        self.transfer_config = TransferConfig(
            multipart_threshold=multipart_part_size,
            multipart_chunksize=multipart_part_size,
            use_threads=True,
        )

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        value = prefix.strip().strip("/")
        if not value:
            return ""
        return normalize_storage_key(value)

    def _object_key(self, path: str) -> str:
        key = normalize_storage_key(path)
        return f"{self.prefix}/{key}" if self.prefix else key

    @property
    def is_object_storage(self) -> bool:
        return True

    @property
    def supports_presigned_urls(self) -> bool:
        return True

    @property
    def supports_multipart_upload(self) -> bool:
        return True

    async def store(self, data: bytes, path: str) -> str:
        key = normalize_storage_key(path)
        checksum = hashlib.sha256(data).hexdigest()
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=self._object_key(key),
            Body=data,
            Metadata={"sha256": checksum},
        )
        return key

    async def retrieve(self, path: str) -> bytes:
        key = normalize_storage_key(path)
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except ClientError as exc:
            self._raise_not_found(exc, key)
            raise
        body = response["Body"]
        try:
            return await asyncio.to_thread(body.read)
        finally:
            body.close()

    async def delete(self, path: str) -> bool:
        key = normalize_storage_key(path)
        if not await self.exists(key):
            return False
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=self.bucket,
            Key=self._object_key(key),
        )
        return True

    async def exists(self, path: str) -> bool:
        try:
            await self.stat(path)
            return True
        except FileNotFoundError:
            return False

    async def stat(self, path: str) -> StorageObjectInfo:
        key = normalize_storage_key(path)
        try:
            response = await asyncio.to_thread(
                self.client.head_object,
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except ClientError as exc:
            self._raise_not_found(exc, key)
            raise
        metadata = response.get("Metadata") or {}
        etag = str(response.get("ETag") or "").strip('"') or None
        checksum = metadata.get("sha256")
        return StorageObjectInfo(
            key=key,
            size=int(response["ContentLength"]),
            etag=etag,
            checksum_sha256=checksum.lower() if checksum else None,
        )

    async def iter_chunks(self, path: str, *, chunk_size: int) -> AsyncIterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        key = normalize_storage_key(path)
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except ClientError as exc:
            self._raise_not_found(exc, key)
            raise
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    async def store_file(
        self,
        source_path: Path,
        path: str,
        *,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
    ) -> str:
        key = normalize_storage_key(path)
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if checksum_sha256:
            extra_args["Metadata"] = {"sha256": checksum_sha256.lower()}
        await asyncio.to_thread(
            self.client.upload_file,
            str(source_path),
            self.bucket,
            self._object_key(key),
            ExtraArgs=extra_args or None,
            Config=self.transfer_config,
        )
        return key

    async def presign_download(
        self,
        path: str,
        *,
        expires_seconds: int,
        response_content_type: str | None = None,
        response_content_disposition: str | None = None,
    ) -> str:
        key = normalize_storage_key(path)
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": self._object_key(key)}
        if response_content_type:
            params["ResponseContentType"] = response_content_type
        if response_content_disposition:
            params["ResponseContentDisposition"] = response_content_disposition
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )

    async def presign_upload(
        self,
        path: str,
        *,
        expires_seconds: int,
        content_type: str,
        checksum_sha256: str | None = None,
    ) -> str:
        key = normalize_storage_key(path)
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self._object_key(key),
            "ContentType": content_type,
        }
        if checksum_sha256:
            params["Metadata"] = {"sha256": checksum_sha256.lower()}
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )

    async def create_multipart_upload(
        self,
        path: str,
        *,
        content_type: str,
        checksum_sha256: str | None = None,
    ) -> MultipartUpload:
        key = normalize_storage_key(path)
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": self._object_key(key),
            "ContentType": content_type,
        }
        if checksum_sha256:
            kwargs["Metadata"] = {"sha256": checksum_sha256.lower()}
        response = await asyncio.to_thread(self.client.create_multipart_upload, **kwargs)
        return MultipartUpload(key=key, upload_id=response["UploadId"])

    async def presign_multipart_part(
        self,
        upload: MultipartUpload,
        *,
        part_number: int,
        expires_seconds: int,
    ) -> str:
        if part_number < 1 or part_number > 10_000:
            raise ValueError("part_number must be between 1 and 10000")
        key = normalize_storage_key(upload.key)
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": self._object_key(key),
                "UploadId": upload.upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_seconds,
        )

    async def complete_multipart_upload(
        self,
        upload: MultipartUpload,
        *,
        parts: list[CompletedPart],
    ) -> StorageObjectInfo:
        if not parts:
            raise ValueError("At least one multipart part is required")
        ordered = sorted(parts, key=lambda part: part.part_number)
        if len({part.part_number for part in ordered}) != len(ordered):
            raise ValueError("Multipart part numbers must be unique")
        key = normalize_storage_key(upload.key)
        await asyncio.to_thread(
            self.client.complete_multipart_upload,
            Bucket=self.bucket,
            Key=self._object_key(key),
            UploadId=upload.upload_id,
            MultipartUpload={
                "Parts": [
                    {"ETag": part.etag, "PartNumber": part.part_number} for part in ordered
                ]
            },
        )
        return await self.stat(key)

    async def abort_multipart_upload(self, upload: MultipartUpload) -> None:
        key = normalize_storage_key(upload.key)
        await asyncio.to_thread(
            self.client.abort_multipart_upload,
            Bucket=self.bucket,
            Key=self._object_key(key),
            UploadId=upload.upload_id,
        )

    @staticmethod
    def _raise_not_found(exc: ClientError, key: str) -> None:
        error = exc.response.get("Error", {})
        code = str(error.get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            raise FileNotFoundError(f"File not found: {key}") from exc
