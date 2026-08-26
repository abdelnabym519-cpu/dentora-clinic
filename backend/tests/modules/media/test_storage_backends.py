"""Scalable media storage adapter integration contracts."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.modules.media.storage import (
    CompletedPart,
    MultipartUpload,
    S3StorageBackend,
    StorageBackend,
    normalize_storage_key,
)


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True
        self._stream.close()


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.presigned: list[tuple[str, dict, int]] = []
        self.completed: list[dict] = []
        self.aborted: list[dict] = []
        self.last_body: _Body | None = None
        self._upload_seq = 0

    @staticmethod
    def _not_found(operation: str) -> ClientError:
        return ClientError(
            {
                "Error": {"Code": "NoSuchKey", "Message": "missing"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            },
            operation,
        )

    def put_object(self, **kwargs):
        payload = bytes(kwargs["Body"])
        self.objects[kwargs["Key"]] = (payload, dict(kwargs.get("Metadata") or {}))
        return {"ETag": '"etag"'}

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise self._not_found("GetObject")
        body = _Body(self.objects[Key][0])
        self.last_body = body
        return {"Body": body}

    def head_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise self._not_found("HeadObject")
        payload, metadata = self.objects[Key]
        return {"ContentLength": len(payload), "ETag": '"etag"', "Metadata": metadata}

    def delete_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        self.objects.pop(Key, None)
        return {}

    def upload_file(
        self,
        Filename: str,  # noqa: N803
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        ExtraArgs=None,  # noqa: N803
        Config=None,  # noqa: N803
    ) -> None:
        del Bucket, Config
        metadata = dict((ExtraArgs or {}).get("Metadata") or {})
        self.objects[Key] = (Path(Filename).read_bytes(), metadata)

    def generate_presigned_url(self, method: str, *, Params: dict, ExpiresIn: int):  # noqa: N803
        self.presigned.append((method, Params, ExpiresIn))
        return f"https://storage.invalid/{method}/{Params['Key']}"

    def create_multipart_upload(self, **kwargs):
        self._upload_seq += 1
        return {"UploadId": f"upload-{self._upload_seq}"}

    def complete_multipart_upload(self, **kwargs):
        self.completed.append(kwargs)
        return {}

    def abort_multipart_upload(self, **kwargs):
        self.aborted.append(kwargs)
        return {}


class _LegacyByteStorage(StorageBackend):
    """Old-style adapter proving optional scalable methods stay compatible."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def store(self, data: bytes, path: str) -> str:
        key = normalize_storage_key(path)
        self.objects[key] = data
        return key

    async def retrieve(self, path: str) -> bytes:
        key = normalize_storage_key(path)
        try:
            return self.objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    async def delete(self, path: str) -> bool:
        key = normalize_storage_key(path)
        return self.objects.pop(key, None) is not None

    async def exists(self, path: str) -> bool:
        return normalize_storage_key(path) in self.objects


@pytest.mark.asyncio
async def test_s3_round_trip_streaming_checksum_prefix_and_delete() -> None:
    client = _FakeS3Client()
    storage = S3StorageBackend(
        bucket="dentora-private",
        prefix="private-media",
        multipart_part_size=5 * 1024 * 1024,
        client=client,
    )
    payload = b"abcdefgh"
    checksum = hashlib.sha256(payload).hexdigest()

    key = await storage.store(payload, "clinic-a/patient-a/scan.stl")
    assert key == "clinic-a/patient-a/scan.stl"
    assert client.objects["private-media/clinic-a/patient-a/scan.stl"][1] == {"sha256": checksum}

    info = await storage.stat(key)
    assert info.key == key
    assert info.size == len(payload)
    assert info.checksum_sha256 == checksum
    assert await storage.retrieve(key) == payload

    chunks = [chunk async for chunk in storage.iter_chunks(key, chunk_size=3)]
    assert chunks == [b"abc", b"def", b"gh"]
    assert client.last_body is not None
    assert client.last_body.closed is True
    assert all(size == 3 for size in client.last_body.read_sizes)

    assert await storage.delete(key) is True
    assert await storage.delete(key) is False
    assert await storage.exists(key) is False


@pytest.mark.asyncio
async def test_s3_file_upload_presigned_and_multipart_contract(tmp_path: Path) -> None:
    client = _FakeS3Client()
    storage = S3StorageBackend(
        bucket="dentora-private",
        prefix="tenant-root",
        multipart_part_size=5 * 1024 * 1024,
        client=client,
    )
    key = "clinic-b/patient-b/model.stl"
    payload = b"stored-through-file"
    checksum = hashlib.sha256(payload).hexdigest()
    source = tmp_path / "model.stl"
    source.write_bytes(payload)

    assert (
        await storage.store_file(
            source,
            key,
            content_type="model/stl",
            checksum_sha256=checksum,
        )
        == key
    )
    assert (await storage.stat(key)).checksum_sha256 == checksum

    upload_url = await storage.presign_upload(
        key,
        expires_seconds=120,
        content_type="model/stl",
        checksum_sha256=checksum,
    )
    assert upload_url.startswith("https://storage.invalid/put_object/")
    method, params, expires = client.presigned[-1]
    assert method == "put_object"
    assert expires == 120
    assert params == {
        "Bucket": "dentora-private",
        "Key": "tenant-root/clinic-b/patient-b/model.stl",
        "ContentType": "model/stl",
        "Metadata": {"sha256": checksum},
    }
    assert "ACL" not in params

    download_url = await storage.presign_download(
        key,
        expires_seconds=60,
        response_content_type="model/stl",
        response_content_disposition='attachment; filename="model.stl"',
    )
    assert download_url.startswith("https://storage.invalid/get_object/")

    upload = await storage.create_multipart_upload(
        key,
        content_type="model/stl",
        checksum_sha256=checksum,
    )
    assert upload == MultipartUpload(key=key, upload_id="upload-1")
    part_url = await storage.presign_multipart_part(upload, part_number=1, expires_seconds=90)
    assert part_url.startswith("https://storage.invalid/upload_part/")
    with pytest.raises(ValueError, match="between 1 and 10000"):
        await storage.presign_multipart_part(upload, part_number=0, expires_seconds=90)

    info = await storage.complete_multipart_upload(
        upload,
        parts=[
            CompletedPart(part_number=2, etag="etag-2"),
            CompletedPart(part_number=1, etag="etag-1"),
        ],
    )
    assert info.size == len(payload)
    assert client.completed[-1]["MultipartUpload"]["Parts"] == [
        {"ETag": "etag-1", "PartNumber": 1},
        {"ETag": "etag-2", "PartNumber": 2},
    ]

    abort_upload = MultipartUpload(key=key, upload_id="upload-abort")
    await storage.abort_multipart_upload(abort_upload)
    assert client.aborted[-1]["UploadId"] == "upload-abort"


@pytest.mark.asyncio
async def test_legacy_byte_adapter_keeps_metadata_and_chunk_compatibility() -> None:
    storage = _LegacyByteStorage()
    await storage.store(b"legacy-data", "legacy/object.bin")

    info = await storage.stat("legacy/object.bin")
    assert info.size == len(b"legacy-data")
    assert [chunk async for chunk in storage.iter_chunks("legacy/object.bin", chunk_size=4)] == [
        b"lega",
        b"cy-d",
        b"ata",
    ]


@pytest.mark.parametrize(
    "key",
    ["", "/absolute", "../escape", "clinic/../escape", "clinic//object", "clinic\\object"],
)
def test_storage_key_rejects_unsafe_paths(key: str) -> None:
    with pytest.raises(ValueError):
        normalize_storage_key(key)
