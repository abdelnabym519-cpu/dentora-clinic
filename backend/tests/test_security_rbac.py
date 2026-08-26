"""Security regression tests for least-privilege RBAC boundaries."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership
from app.core.auth.permissions import has_permission
from app.modules.patients.models import Patient

RECEPTIONIST_DENIED_CLINICAL_PERMISSIONS = (
    "clinical_notes.notes.read",
    "clinical_notes.notes.write",
    "media.documents.read",
    "media.documents.write",
    "media.attachments.read",
    "media.attachments.write",
    "odontogram.read",
    "odontogram.write",
    "odontogram.treatments.read",
    "odontogram.treatments.write",
    "patients_clinical.medical.read",
    "patients_clinical.medical.write",
    "admin.users.read",
    "admin.users.write",
    "admin.clinic.write",
)

RECEPTIONIST_ALLOWED_FRONT_DESK_PERMISSIONS = (
    "patients.read",
    "patients.write",
    "patients_clinical.emergency.read",
    "patients_clinical.emergency.write",
    "agenda.appointments.read",
    "agenda.appointments.write",
    "billing.read",
    "billing.write",
    "payments.record.read",
    "payments.record.write",
)


@pytest.mark.parametrize("permission", RECEPTIONIST_DENIED_CLINICAL_PERMISSIONS)
def test_receptionist_cannot_cross_clinical_or_admin_boundaries(permission: str) -> None:
    assert not has_permission("receptionist", permission)


@pytest.mark.parametrize("permission", RECEPTIONIST_ALLOWED_FRONT_DESK_PERMISSIONS)
def test_receptionist_keeps_required_front_desk_permissions(permission: str) -> None:
    assert has_permission("receptionist", permission)


@pytest.mark.parametrize("role", ("admin", "dentist"))
@pytest.mark.parametrize(
    "permission",
    ("clinical_notes.notes.read", "clinical_notes.notes.write"),
)
def test_privileged_clinical_roles_keep_clinical_notes_access(role: str, permission: str) -> None:
    assert has_permission(role, permission)


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
async def test_receptionist_cannot_read_clinical_notes_endpoint(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    await _change_current_membership_to_receptionist(db_session, test_clinic.id)

    response = await client.get(
        "/api/v1/clinical_notes/notes",
        headers=auth_headers,
        params={"owner_type": "patient", "owner_id": str(test_patient.id)},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_receptionist_cannot_write_clinical_notes_endpoint(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    await _change_current_membership_to_receptionist(db_session, test_clinic.id)

    response = await client.post(
        "/api/v1/clinical_notes/notes",
        headers=auth_headers,
        json={
            "note_type": "diagnosis",
            "owner_type": "patient",
            "owner_id": str(test_patient.id),
            "body": "Reception must not create clinical notes",
        },
    )

    assert response.status_code == 403
