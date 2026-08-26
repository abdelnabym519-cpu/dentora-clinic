"""Database-level integrity regression tests for core tenant boundaries."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User


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
