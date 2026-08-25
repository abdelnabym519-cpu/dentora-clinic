from __future__ import annotations

import hashlib
from io import BytesIO

import pytest

from app.modules.media.storage import get_storage_backend, set_test_storage_path
from app.modules.media.storage.configuration import S3StorageConfig
from app.modules.media.storage.local import LocalStorageBackend
from app.modules.media.storage.s3 import S3StorageBackend


async def _chunks(*values: bytes):
    for value in values:
        yield value


class _Body:
    def __init__(self, data: bytes) -> None:
        self._stream = BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.uploads: dict[str, dict] = {}
        self._upload_sequence = 0

    def put_object(self, **kwargs):
        data = bytes(kwargs["Body"])
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "data": data,
            "metadata": dict(kwargs.get("Metadata") or {}),
            "content_type": kwargs.get("ContentType"),
        }
        return {"ETag": f'"etag-{len(data)}"'}

    def get_object(self, **kwargs):
        item = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": _Body(item["data"])}

    def head_object(self, **kwargs):
        item = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {
            "ContentLength": len(item["data"]),
            "ETag": f'"etag-{len(item["data"])}"',
            "Metadata": item["metadata"],
        }

    def delete_object(self, **kwargs):
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
        return {}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn, HttpMethod=None):
        method = HttpMethod or "GET"
        return f"https://signed.invalid/{operation}/{Params['Key']}?method={method}&expires={ExpiresIn}"

    def create_multipart_upload(self, **kwargs):
        self._upload_sequence += 1
        upload_id = f"upload-{self._upload_sequence}"
        self.uploads[upload_id] = {"kwargs": kwargs, "parts": {}}
        return {"UploadId": upload_id}

    def upload_part(self, **kwargs):
        upload = self.uploads[kwargs["UploadId"]]
        upload["parts"][kwargs["PartNumber"]] = bytes(kwargs["Body"])
        return {"ETag": f'"part-{kwargs["PartNumber"]}"'}

    def complete_multipart_upload(self, **kwargs):
        upload = self.uploads.pop(kwargs["UploadId"])
        ordered = b"".join(upload["parts"][part["PartNumber"]] for part in kwargs["MultipartUpload"]["Parts"])
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "data": ordered,
            "metadata": {},
            "content_type": upload["kwargs"].get("ContentType"),
        }
        return {"ETag": '"multipart-etag"'}

    def abort_multipart_upload(self, **kwargs):
        self.uploads.pop(kwargs["UploadId"], None)
        return {}


def _s3_config(*, threshold: int = 8, part_size: int = 5) -> S3StorageConfig:
    return S3StorageConfig(
        endpoint_url="http://minio.invalid:9000",
        region_name="us-east-1",
        bucket="dentora-test",
        access_key="test-access",
        secret_key="test-secret",
        prefix="dentora",
        presign_expiry_seconds=900,
        multipart_threshold_bytes=threshold,
        multipart_part_size_bytes=part_size,
        addressing_style="path",
    )


@pytest.mark.asyncio
async def test_local_backend_stream_round_trip_and_integrity(tmp_path) -> None:
    backend = LocalStorageBackend(str(tmp_path))
    result = await backend.store_stream(_chunks(b"abc", b"def"), "clinic/patient/media.bin")
    assert result.size == 6
    assert result.checksum_sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert b"".join([chunk async for chunk in backend.iter_bytes(result.path, chunk_size=2)]) == b"abcdef"
    assert (await backend.stat(result.path)).checksum_sha256 == result.checksum_sha256


@pytest.mark.asyncio
async def test_local_backend_rejects_path_traversal(tmp_path) -> None:
    backend = LocalStorageBackend(str(tmp_path))
    with pytest.raises(ValueError):
        await backend.store(b"secret", "../escape.bin")
    with pytest.raises(ValueError):
        await backend.store(b"secret", "/absolute.bin")


def test_s3_config_rejects_missing_or_partial_credentials(monkeypatch) -> None:
    monkeypatch.delenv("S3_BUCKET", raising=False)
    with pytest.raises(ValueError, match="S3_BUCKET"):
        S3StorageConfig.from_env()

    monkeypatch.setenv("S3_BUCKET", "dentora")
    monkeypatch.setenv("S3_ACCESS_KEY", "only-one-half")
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="configured together"):
        S3StorageConfig.from_env()


@pytest.mark.asyncio
async def test_factory_preserves_local_backend(tmp_path) -> None:
    set_test_storage_path(str(tmp_path))
    try:
        backend = get_storage_backend("local")
        assert isinstance(backend, LocalStorageBackend)
    finally:
        set_test_storage_path(None)


@pytest.mark.asyncio
async def test_s3_backend_streams_multipart_and_presigns_private_keys() -> None:
    backend = S3StorageBackend(_s3_config())
    fake = _FakeS3Client()
    backend._client = fake

    result = await backend.store_stream(
        _chunks(b"abcdef", b"ghijkl"),
        "clinic-a/patient-a/asset.bin",
        content_type="application/octet-stream",
        content_length=12,
    )
    assert result.size == 12
    assert result.checksum_sha256 == hashlib.sha256(b"abcdefghijkl").hexdigest()
    assert await backend.retrieve(result.path) == b"abcdefghijkl"
    assert await backend.exists(result.path) is True

    url = await backend.presign_download(result.path, expires_seconds=60)
    assert url is not None
    assert "dentora/clinic-a/patient-a/asset.bin" in url
    assert "expires=60" in url

    put_url = await backend.presign_upload(
        "clinic-a/patient-a/new.bin",
        expires_seconds=60,
        content_type="application/octet-stream",
    )
    assert put_url is not None
    assert "method=PUT" in put_url


@pytest.mark.asyncio
async def test_s3_backend_rejects_arbitrary_object_key() -> None:
    backend = S3StorageBackend(_s3_config())
    backend._client = _FakeS3Client()
    with pytest.raises(ValueError):
        await backend.store(b"x", "../../other-clinic/object")
