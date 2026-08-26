"""Binary storage regression coverage for all supported intraoral mesh formats."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.models import Document
from app.modules.media.service import DocumentService
from app.modules.patients.models import Patient


def _binary_stl() -> bytes:
    return b"dentora-stl".ljust(80, b"\0") + (1).to_bytes(4, "little") + b"\0" * 50


OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
PLY = (
    b"ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\n"
    b"property float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n"
    b"0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "mime_type", "payload", "expected_format"),
    [
        ("scan.stl", "model/stl", _binary_stl(), "stl"),
        ("scan.obj", "model/obj", OBJ, "obj"),
        ("scan.ply", "model/ply", PLY, "ply"),
    ],
)
async def test_mesh_binary_round_trip_for_every_supported_format(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
    filename: str,
    mime_type: str,
    payload: bytes,
    expected_format: str,
) -> None:
    response = await client.post(
        f"/api/v1/dental_3d/patients/{test_patient.id}/meshes",
        headers=auth_headers,
        files={"file": (filename, payload, mime_type)},
    )

    assert response.status_code == 201
    descriptor = response.json()["data"]
    assert descriptor["format"] == expected_format

    document_id = UUID(descriptor["document_id"])
    document = (
        await db_session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one()
    assert document.clinic_id == test_patient.clinic_id
    assert document.patient_id == test_patient.id
    assert document.file_size == len(payload)
    assert await DocumentService.download_document(document) == payload
