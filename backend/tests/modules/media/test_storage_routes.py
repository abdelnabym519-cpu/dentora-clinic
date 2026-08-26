from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.media.models import Document
from app.modules.patients.models import Patient


@pytest.mark.asyncio
async def test_stream_download_round_trips_binary(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
) -> None:
    payload = b"%PDF-1.4\nstreaming-test\n%%EOF"
    upload = await client.post(
        f"/api/v1/media/patients/{test_patient.id}/documents",
        headers=auth_headers,
        files={"file": ("stream.pdf", BytesIO(payload), "application/pdf")},
        data={"document_type": "report", "title": "Streaming"},
    )
    assert upload.status_code == 201
    document_id = upload.json()["data"]["id"]

    response = await client.get(
        f"/api/v1/media/documents/{document_id}/stream",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-length"] == str(len(payload))
    assert "attachment" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_local_backend_does_not_fake_presigned_url(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
) -> None:
    upload = await client.post(
        f"/api/v1/media/patients/{test_patient.id}/documents",
        headers=auth_headers,
        files={"file": ("local.pdf", BytesIO(b"%PDF-local"), "application/pdf")},
        data={"document_type": "report", "title": "Local"},
    )
    document_id = upload.json()["data"]["id"]

    response = await client.get(
        f"/api/v1/media/documents/{document_id}/presigned-download",
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_presigned_download_requires_clinic_authorization(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user"]["id"]
    other_clinic = Clinic(id=uuid4(), name="Other Media Clinic", tax_id="MEDIA-OTHER", settings={})
    db_session.add(other_clinic)
    await db_session.flush()
    other_patient = Patient(
        id=uuid4(),
        clinic_id=other_clinic.id,
        first_name="Other",
        last_name="Patient",
    )
    db_session.add(other_patient)
    await db_session.flush()
    document = Document(
        id=uuid4(),
        clinic_id=other_clinic.id,
        patient_id=other_patient.id,
        document_type="report",
        title="Private",
        original_filename="private.pdf",
        storage_path=f"{other_clinic.id}/{other_patient.id}/{uuid4()}.pdf",
        mime_type="application/pdf",
        file_size=7,
        uploaded_by=user_id,
        status="active",
        tags=[],
        extra_data={"storage_backend": "s3"},
    )
    db_session.add(document)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/media/documents/{document.id}/presigned-download",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_authorized_s3_presign_uses_server_selected_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch,
) -> None:
    upload = await client.post(
        f"/api/v1/media/patients/{test_patient.id}/documents",
        headers=auth_headers,
        files={"file": ("signed.pdf", BytesIO(b"%PDF-signed"), "application/pdf")},
        data={"document_type": "report", "title": "Signed"},
    )
    document_id = upload.json()["data"]["id"]
    captured: dict[str, object] = {}

    class FakeS3:
        supports_presigned_urls = True
        config = SimpleNamespace(presign_expiry_seconds=321)

        async def presign_download(self, path, *, expires_seconds, content_disposition=None):
            captured.update(
                path=path,
                expires_seconds=expires_seconds,
                content_disposition=content_disposition,
            )
            return "https://signed.example.test/object?token=opaque"

    monkeypatch.setattr(
        "app.modules.media.storage_router.get_document_storage_backend",
        lambda document: FakeS3(),
    )

    response = await client.get(
        f"/api/v1/media/documents/{document_id}/presigned-download",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["expires_in_seconds"] == 321
    assert captured["path"]
    assert "signed.pdf" not in str(captured["path"])
