"""Phase 5.1 API, geometry composition, RBAC and clinic-isolation coverage."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.modules.dental_3d.infrastructure import CbctDicomGeometrySource
from app.modules.media.models import Document as MediaDocument
from app.modules.patients.models import Patient
from tests.modules.dental_3d.test_cbct_ingestion import dicom_bytes


def _upload_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/cbct/dicom-instances"


def _scene_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/scene"


async def _receptionist_headers(db: AsyncSession, clinic_id) -> dict[str, str]:
    user = User(
        id=uuid4(),
        email=f"cbct-recep-{uuid4().hex[:8]}@test.clinic",
        password_hash=hash_password("TestPass1234"),
        first_name="CBCT",
        last_name="Receptionist",
    )
    db.add(user)
    await db.flush()
    db.add(
        ClinicMembership(
            id=uuid4(),
            user_id=user.id,
            clinic_id=clinic_id,
            role="receptionist",
        )
    )
    await db.commit()
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_cbct_ingestion_foundation_end_to_end_security_and_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    """One fixture lifecycle covers the complete Phase 5.1 API boundary."""
    study_uid = "1.2.826.0.1.3680043.8.498.51"
    series_uid = "1.2.826.0.1.3680043.8.498.52"

    receipts = []
    for instance in (1, 2):
        response = await client.post(
            _upload_url(test_patient.id),
            headers=auth_headers,
            files={
                "file": (
                    f"slice-{instance}.dcm",
                    dicom_bytes(
                        study_uid=study_uid,
                        series_uid=series_uid,
                        instance_number=instance,
                    ),
                    "application/dicom",
                )
            },
        )
        assert response.status_code == 201
        receipts.append(response.json()["data"])
        assert receipts[-1]["metadata"]["modality"] == "CT"
        assert receipts[-1]["non_diagnostic"] is True

    scene_response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
    assert scene_response.status_code == 200
    scene = scene_response.json()["data"]
    # Availability does not masquerade as renderable/patient-aligned geometry.
    assert scene["generator"] == "synthetic"
    assert scene["meshes"] == []
    assert len(scene["teeth"]) == 32
    assert len(scene["cbct_series"]) == 1
    series = scene["cbct_series"][0]
    assert series["study_instance_uid"] == study_uid
    assert series["series_instance_uid"] == series_uid
    assert series["instance_count"] == 2
    assert series["frame_count"] == 2
    assert series["catalog_truncated"] is False
    assert series["non_diagnostic"] is True
    assert set(series["document_ids"]) == {item["document_id"] for item in receipts}

    # The raw object remains protected by the existing media authorization.
    download = await client.get(receipts[0]["download_url"], headers=auth_headers)
    assert download.status_code == 200
    assert download.content[128:132] == b"DICM"

    # Unknown/cross-clinic patients are hidden before file processing.
    other_clinic = Clinic(
        id=uuid4(), name="Other Clinic", tax_id="B55555555", address={"city": "Elsewhere"}
    )
    db_session.add(other_clinic)
    other_patient = Patient(
        id=uuid4(),
        clinic_id=other_clinic.id,
        first_name="Other",
        last_name="Patient",
        email="cbct-other@example.test",
        phone="+34600000055",
    )
    db_session.add(other_patient)
    await db_session.commit()
    cross_clinic = await client.post(
        _upload_url(other_patient.id),
        headers=auth_headers,
        files={"file": ("slice.dcm", dicom_bytes(), "application/dicom")},
    )
    assert cross_clinic.status_code == 404
    invisible = await CbctDicomGeometrySource(db_session).provide(other_clinic.id, test_patient.id)
    assert invisible.cbct_series == []

    # Existing dental_3d RBAC remains authoritative; no new permission path.
    receptionist = await _receptionist_headers(db_session, test_patient.clinic_id)
    forbidden = await client.post(
        _upload_url(test_patient.id),
        headers=receptionist,
        files={"file": ("slice.dcm", dicom_bytes(), "application/dicom")},
    )
    assert forbidden.status_code == 403

    # Server-side modality validation rejects non-CT data with a stable code.
    wrong_modality = await client.post(
        _upload_url(test_patient.id),
        headers=auth_headers,
        files={
            "file": (
                "mr.dcm",
                dicom_bytes(modality="MR"),
                "application/dicom",
            )
        },
    )
    assert wrong_modality.status_code == 400
    assert wrong_modality.json()["message"].startswith("unsupported_modality:")

    invalid_request = await client.post(
        _upload_url(test_patient.id),
        headers=auth_headers,
        files={"file": (f"{'x' * 260}.dcm", dicom_bytes(), "application/dicom")},
    )
    assert invalid_request.status_code == 400
    assert invalid_request.json()["message"].startswith("invalid_request:")

    # Media archival immediately removes instances from CBCT availability.
    first_document = (
        await db_session.execute(
            select(MediaDocument).where(MediaDocument.id == receipts[0]["document_id"])
        )
    ).scalar_one()
    first_document.status = "archived"
    await db_session.flush()
    provision = await CbctDicomGeometrySource(db_session).provide(
        test_patient.clinic_id, test_patient.id
    )
    assert provision.cbct_series[0].instance_count == 1

    second_document = (
        await db_session.execute(
            select(MediaDocument).where(MediaDocument.id == receipts[1]["document_id"])
        )
    ).scalar_one()
    second_document.status = "archived"
    await db_session.flush()
    provision = await CbctDicomGeometrySource(db_session).provide(
        test_patient.clinic_id, test_patient.id
    )
    assert provision.cbct_series == []
