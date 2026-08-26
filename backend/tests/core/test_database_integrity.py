"""Database-level integrity regression tests for core tenant boundaries."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.modules.ai_case_summary.models import AICaseSummaryRecord
from app.modules.case_intelligence.models import CaseSnapshotRecord
from app.modules.patients.models import Patient
from app.modules.patients_clinical.models import Allergy


async def _tenant_fixture(db_session: AsyncSession) -> tuple[User, Clinic]:
    user = User(
        id=uuid4(),
        email=f"db-integrity-{uuid4()}@example.test",
        password_hash="not-used",
        first_name="DB",
        last_name="Integrity",
    )
    clinic = Clinic(
        id=uuid4(),
        name="DB Integrity Clinic",
        tax_id=f"T{str(uuid4())[:12]}",
        settings={},
    )
    db_session.add_all([user, clinic])
    await db_session.flush()
    return user, clinic


async def _cross_tenant_patient_fixture(
    db_session: AsyncSession,
) -> tuple[Clinic, Clinic, Patient]:
    clinic_a = Clinic(
        id=uuid4(),
        name="Clinic A",
        tax_id=f"A{str(uuid4())[:12]}",
        settings={},
    )
    clinic_b = Clinic(
        id=uuid4(),
        name="Clinic B",
        tax_id=f"B{str(uuid4())[:12]}",
        settings={},
    )
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic_a.id,
        first_name="Tenant",
        last_name="Bound",
    )
    db_session.add_all([clinic_a, clinic_b, patient])
    await db_session.flush()
    return clinic_a, clinic_b, patient


@pytest.mark.asyncio
async def test_membership_rejects_duplicate_user_clinic(
    db_session: AsyncSession,
) -> None:
    """A user has exactly one authoritative RBAC row in a clinic."""
    user, clinic = await _tenant_fixture(db_session)
    db_session.add(
        ClinicMembership(
            id=uuid4(),
            user_id=user.id,
            clinic_id=clinic.id,
            role="dentist",
        )
    )
    await db_session.flush()

    db_session.add(
        ClinicMembership(
            id=uuid4(),
            user_id=user.id,
            clinic_id=clinic.id,
            role="assistant",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_membership_rejects_unknown_role(db_session: AsyncSession) -> None:
    """Direct writes cannot persist a role outside the RBAC domain."""
    user, clinic = await _tenant_fixture(db_session)
    db_session.add(
        ClinicMembership(
            id=uuid4(),
            user_id=user.id,
            clinic_id=clinic.id,
            role="owner_without_permissions",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_clinical_row_rejects_cross_clinic_patient(
    db_session: AsyncSession,
) -> None:
    """Clinical data cannot claim a tenant different from its patient."""
    _, clinic_b, patient = await _cross_tenant_patient_fixture(db_session)

    db_session.add(
        Allergy(
            id=uuid4(),
            patient_id=patient.id,
            clinic_id=clinic_b.id,
            name="test-allergen",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_case_snapshot_rejects_cross_clinic_patient(
    db_session: AsyncSession,
) -> None:
    """Case Intelligence cannot materialize a patient under another clinic."""
    _, clinic_b, patient = await _cross_tenant_patient_fixture(db_session)

    db_session.add(
        CaseSnapshotRecord(
            id=uuid4(),
            clinic_id=clinic_b.id,
            patient_id=patient.id,
            snapshot_version=1,
            contract_version="1.0",
            source_digest="sha256:" + ("a" * 64),
            snapshot_data={},
            source_versions={},
            generated_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_ai_case_summary_rejects_cross_clinic_patient(
    db_session: AsyncSession,
) -> None:
    """AI summaries cannot claim a tenant different from their patient."""
    _, clinic_b, patient = await _cross_tenant_patient_fixture(db_session)
    digest = "sha256:" + ("b" * 64)

    db_session.add(
        AICaseSummaryRecord(
            id=uuid4(),
            clinic_id=clinic_b.id,
            patient_id=patient.id,
            summary_version=1,
            contract_version="1.0",
            case_snapshot_version=1,
            case_snapshot_contract_version="1.0",
            case_source_digest=digest,
            provider_name="test",
            model_name="test-model",
            provider_contract_version="1.0",
            prompt_version="1.0",
            input_digest=digest,
            output_digest=digest,
            summary_data={},
            review_status="pending_review",
            generated_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
