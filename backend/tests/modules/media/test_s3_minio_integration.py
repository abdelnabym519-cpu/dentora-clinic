from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import pytest

from app.modules.media.storage.configuration import S3StorageConfig
from app.modules.media.storage.s3 import S3StorageBackend

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_S3_INTEGRATION") != "1",
    reason="requires an explicit MinIO/S3 integration environment",
)


async def _chunks(payload: bytes, chunk_size: int = 1024 * 1024):
    for offset in range(0, len(payload), chunk_size):
        yield payload[offset : offset + chunk_size]


@pytest.mark.asyncio
async def test_minio_private_stream_multipart_round_trip() -> None:
    backend = S3StorageBackend(S3StorageConfig.from_env())
    try:
        backend._client.create_bucket(Bucket=backend.config.bucket)
    except backend._client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except backend._client.exceptions.BucketAlreadyExists:
        pass

    path = f"clinics/{uuid4()}/patients/{uuid4()}/media/{uuid4()}.bin"
    payload = b"dentora-minio" * (500_000)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    result = await backend.store_stream(
        _chunks(payload),
        path,
        content_type="application/octet-stream",
        content_length=len(payload),
    )

    persisted = await backend.stat(path)
    assert result.size == len(payload)
    assert result.checksum_sha256 == expected_sha256
    assert persisted.size == len(payload)
    assert persisted.checksum_sha256 == expected_sha256
    assert await backend.retrieve(path) == payload
    assert await backend.presign_download(path, expires_seconds=60)
    assert await backend.delete(path) is True
    assert await backend.exists(path) is False
