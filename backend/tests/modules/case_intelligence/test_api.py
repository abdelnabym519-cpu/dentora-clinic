"""Integration tests for Case Intelligence versioning, RBAC and source immutability."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import ClinicMembership
from app.modules.case_intelligence.models import CaseSnapshotRecord
from app.modules.media.models import Document
from app.modules.odontogram.models import ToothRecord
from app.modules.patients.models import Patient


@pytest.mark.asyncio
async def test_current_snapshot_is_reproducible_append_only_and_does_not_mutate_sources(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    tooth = ToothRecord(
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        tooth_number=11,
        tooth_type="permanent",
        general_condition="healthy",
        surfaces={},
    )
    db_session.add(tooth)
    await db_session.commit()
    original_condition = tooth.general_condition

    path = f"/api/v1/case_intelligence/patients/{test_patient.id}"
    first = await client.get(path, headers=auth_headers)
    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["case_snapshot_version"] == 1
    assert first_data["availability"]["odontogram"] == "available"
    assert first_data["availability"]["alignment"] == "not_available"
    assert first_data["reference_frame"]["status"] == "not_available"

    await db_session.refresh(tooth)
    assert tooth.general_condition == original_condition

    second = await client.get(path, headers=auth_headers)
    assert second.status_code == 200
    assert second.json()["data"] == first_data

    count = await db_session.scalar(
        select(func.count())
        .select_from(CaseSnapshotRecord)
        .where(CaseSnapshotRecord.patient_id == test_patient.id)
    )
    assert count == 1

    tooth.general_condition = "missing"
    await db_session.commit()

    third = await client.get(path, headers=auth_headers)
    assert third.status_code == 200
    third_data = third.json()["data"]
    assert third_data["case_snapshot_version"] == 2
    assert third_data["source_digest"] != first_data["source_digest"]

    historical = await client.get(f"{path}?version=1", headers=auth_headers)
    assert historical.status_code == 200
    assert historical.json()["data"] == first_data

    await db_session.refresh(tooth)
    assert tooth.general_condition == "missing"
    assert original_condition == "healthy"

    count = await db_session.scalar(
        select(func.count())
        .select_from(CaseSnapshotRecord)
        .where(CaseSnapshotRecord.patient_id == test_patient.id)
    )
    assert count == 2


@pytest.mark.asyncio
async def test_case_intelligence_is_tenant_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
) -> None:
    missing_patient_id = UUID(int=test_patient.id.int ^ 1)
    response = await client.get(
        f"/api/v1/case_intelligence/patients/{missing_patient_id}",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_receptionist_without_case_intelligence_permission_is_forbidden(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    membership = await db_session.scalar(
        select(ClinicMembership).where(ClinicMembership.clinic_id == test_patient.clinic_id)
    )
    assert membership is not None
    membership.role = "receptionist"
    await db_session.commit()

    response = await client.get(
        f"/api/v1/case_intelligence/patients/{test_patient.id}",
        headers=auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_native_cbct_and_ios_availability_do_not_require_alignment(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    membership = await db_session.scalar(
        select(ClinicMembership).where(ClinicMembership.clinic_id == test_patient.clinic_id)
    )
    assert membership is not None
    mesh = Document(
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        document_type="other",
        title="IOS fixture",
        original_filename="scan.stl",
        storage_path=f"fixtures/{test_patient.id}/scan.stl",
        mime_type="model/stl",
        file_size=128,
        media_kind="document",
        uploaded_by=membership.user_id,
        status="active",
        tags=["dental-3d", "ios"],
        extra_data={},
    )
    dicom = Document(
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        document_type="other",
        title="CBCT fixture",
        original_filename="slice.dcm",
        storage_path=f"fixtures/{test_patient.id}/slice.dcm",
        mime_type="application/dicom",
        file_size=256,
        media_kind="document",
        uploaded_by=membership.user_id,
        status="active",
        tags=["dental-3d", "cbct", "dicom"],
        extra_data={
            "dental_3d_cbct": {
                "schema_version": 1,
                "metadata": {
                    "source": "dicom",
                    "modality": "CT",
                    "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2",
                    "study_instance_uid": "1.2.826.0.1.3680043.8.498.1",
                    "series_instance_uid": "1.2.826.0.1.3680043.8.498.2",
                    "sop_instance_uid": "1.2.826.0.1.3680043.8.498.3",
                    "transfer_syntax_uid": "1.2.840.10008.1.2.1",
                    "frame_of_reference_uid": "1.2.826.0.1.3680043.8.498.4",
                    "rows": 64,
                    "columns": 64,
                    "number_of_frames": 1,
                },
            }
        },
    )
    db_session.add_all([mesh, dicom])
    await db_session.commit()

    response = await client.get(
        f"/api/v1/case_intelligence/patients/{test_patient.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["availability"]["ios"] == "available"
    assert data["availability"]["cbct"] == "available"
    assert data["availability"]["alignment"] == "not_available"
    assert data["reference_frame"]["status"] == "not_available"
    assert data["clinical_state"]["ios"]["evidence"]
    assert data["clinical_state"]["cbct"]["evidence"]


@pytest.mark.asyncio
async def test_case_snapshot_api_is_read_only_and_rejects_client_snapshot_bodies(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
) -> None:
    response = await client.post(
        f"/api/v1/case_intelligence/patients/{test_patient.id}",
        headers=auth_headers,
        json={"case_snapshot_version": 999, "clinical_state": {}},
    )
    assert response.status_code == 405
