"""Live S3-compatible integration coverage for scalable media storage."""

from __future__ import annotations

import asyncio
import hashlib
import os

import httpx
import pytest

from app.modules.media.storage import CompletedPart, S3StorageBackend

ENDPOINT = os.getenv("S3_INTEGRATION_ENDPOINT", "")
ACCESS_KEY = os.getenv("S3_INTEGRATION_ACCESS_KEY", "")
SECRET_KEY = os.getenv("S3_INTEGRATION_SECRET_KEY", "")
BUCKET = os.getenv("S3_INTEGRATION_BUCKET", "dentora-media-integration")

pytestmark = pytest.mark.skipif(
    not ENDPOINT,
    reason="live S3 integration endpoint is provided by the dedicated CI gate",
)


@pytest.mark.asyncio
async def test_live_private_s3_round_trip_presigned_and_multipart() -> None:
    storage = S3StorageBackend(
        bucket=BUCKET,
        region="us-east-1",
        endpoint_url=ENDPOINT,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        prefix="integration",
        multipart_part_size=5 * 1024 * 1024,
    )
    await asyncio.to_thread(storage.client.create_bucket, Bucket=BUCKET)

    stored_key = "clinic-a/patient-a/round-trip.bin"
    direct_key = "clinic-a/patient-a/direct-upload.bin"
    multipart_key = "clinic-b/patient-b/multipart.bin"
    abort_key = "clinic-b/patient-b/aborted.bin"

    try:
        payload = b"dentora-private-object-storage"
        payload_sha = hashlib.sha256(payload).hexdigest()
        assert await storage.store(payload, stored_key) == stored_key

        info = await storage.stat(stored_key)
        assert info.size == len(payload)
        assert info.checksum_sha256 == payload_sha
        assert await storage.retrieve(stored_key) == payload
        assert b"".join(
            [chunk async for chunk in storage.iter_chunks(stored_key, chunk_size=7)]
        ) == payload

        async with httpx.AsyncClient(timeout=30.0) as client:
            anonymous = await client.get(
                f"{ENDPOINT.rstrip('/')}/{BUCKET}/integration/{stored_key}"
            )
            assert anonymous.status_code == 403

            download_url = await storage.presign_download(
                stored_key,
                expires_seconds=120,
                response_content_type="application/octet-stream",
            )
            download = await client.get(download_url)
            assert download.status_code == 200
            assert download.content == payload

            direct_payload = b"browser-to-private-object-store"
            direct_sha = hashlib.sha256(direct_payload).hexdigest()
            upload_url = await storage.presign_upload(
                direct_key,
                expires_seconds=120,
                content_type="application/octet-stream",
                checksum_sha256=direct_sha,
            )
            direct_upload = await client.put(
                upload_url,
                content=direct_payload,
                headers={
                    "Content-Type": "application/octet-stream",
                    "x-amz-meta-sha256": direct_sha,
                },
            )
            assert direct_upload.status_code == 200
            direct_info = await storage.stat(direct_key)
            assert direct_info.size == len(direct_payload)
            assert direct_info.checksum_sha256 == direct_sha
            assert await storage.retrieve(direct_key) == direct_payload

            first_part = b"a" * (5 * 1024 * 1024)
            second_part = b"tail"
            multipart_payload = first_part + second_part
            multipart_sha = hashlib.sha256(multipart_payload).hexdigest()
            upload = await storage.create_multipart_upload(
                multipart_key,
                content_type="application/octet-stream",
                checksum_sha256=multipart_sha,
            )
            completed_parts: list[CompletedPart] = []
            for part_number, part in enumerate((first_part, second_part), start=1):
                part_url = await storage.presign_multipart_part(
                    upload,
                    part_number=part_number,
                    expires_seconds=120,
                )
                part_upload = await client.put(part_url, content=part)
                assert part_upload.status_code == 200
                etag = part_upload.headers.get("etag")
                assert etag
                completed_parts.append(
                    CompletedPart(part_number=part_number, etag=etag)
                )

            multipart_info = await storage.complete_multipart_upload(
                upload,
                parts=completed_parts,
            )
            assert multipart_info.size == len(multipart_payload)
            assert multipart_info.checksum_sha256 == multipart_sha
            assert await storage.retrieve(multipart_key) == multipart_payload

            aborted = await storage.create_multipart_upload(
                abort_key,
                content_type="application/octet-stream",
            )
            await storage.abort_multipart_upload(aborted)
            assert await storage.exists(abort_key) is False
    finally:
        for key in (stored_key, direct_key, multipart_key):
            await storage.delete(key)
