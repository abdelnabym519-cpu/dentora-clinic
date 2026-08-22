"""RBAC regression tests for the media module."""

from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.core.auth.permissions import has_permission
from app.modules.patients.models import Patient

RECEPTIONIST_DENIED_MEDIA_PERMISSIONS = (
    "media.documents.read",
    "media.documents.write",
    "media.attachments.read",
    "media.attachments.write",
)


@pytest.mark.parametrize("permission", RECEPTIONIST_DENIED_MEDIA_PERMISSIONS)
def test_receptionist_has_no_media_permissions(permission: str) -> None:
    """Reception must not gain access to clinical media."""
    assert not has_permission("receptionist", permission)


async def _change_current_membership_to_receptionist(
    db_session: AsyncSession,
    clinic_id,
) -> None:
    result = await db_session.execute(
        select(ClinicMembership).where(ClinicMembership.clinic_id == clinic_id)
    )
    membership = result.scalar_one()
    membership.role = "receptionist"
    await db_session.commit()


@pytest.mark.asyncio
async def test_receptionist_cannot_list_patient_media(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    """Reception cannot read a patient's documents/photos/X-rays."""
    await _change_current_membership_to_receptionist(
        db_session,
        test_clinic.id,
    )

    response = await client.get(
        f"/api/v1/media/patients/{test_patient.id}/documents",
        headers=auth_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_receptionist_cannot_upload_patient_media(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    """Reception cannot upload documents/photos/X-rays."""
    await _change_current_membership_to_receptionist(
        db_session,
        test_clinic.id,
    )

    response = await client.post(
        f"/api/v1/media/patients/{test_patient.id}/documents",
        headers=auth_headers,
        files={
            "file": (
                "blocked.pdf",
                BytesIO(b"%PDF-1.4\n%%EOF"),
                "application/pdf",
            )
        },
        data={
            "document_type": "other",
            "title": "Blocked receptionist upload",
        },
    )

    assert response.status_code == 403
