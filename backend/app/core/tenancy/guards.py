"""Repository / service-level defense-in-depth guards.

Every multi-clinic query already filters by ``clinic_id`` at the router
boundary. These guards provide a *second*, independent line of defense
inside services and repositories so a single missing ``WHERE`` clause
cannot leak or corrupt another clinic's data.

They are deliberately framework-light: they raise the standard
``PermissionError`` / ``ValueError`` domain errors (which the FastAPI
exception handlers translate to 403/422) so they can be called from
background jobs and CLI code too.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class CrossTenantViolationError(PermissionError):
    """Raised when a row belongs to a different tenant than expected."""


def assert_same_clinic(expected_clinic_id: UUID, actual_clinic_id: UUID | None) -> None:
    """Assert a row belongs to ``expected_clinic_id``.

    Call this after fetching an entity by id without a clinic filter —
    e.g. ``await db.get(Patient, id)`` — before returning or mutating
    it. A mismatched/ownerless row raises 403.
    """
    if actual_clinic_id is None or actual_clinic_id != expected_clinic_id:
        raise PermissionError("Cross-clinic access denied")


async def assert_clinic_in_tenant(
    db: AsyncSession,
    *,
    clinic_id: UUID,
    tenant_id: UUID,
) -> None:
    """Assert ``clinic_id`` exists and is owned by ``tenant_id``.

    Cheap single-row guard used by repository methods that accept a
    clinic id coming from a client-supplied path/body rather than the
    resolved context.
    """
    from app.core.auth.models import Clinic

    result = await db.execute(select(Clinic.tenant_id).where(Clinic.id == clinic_id))
    owner = result.scalar_one_or_none()
    if owner is None:
        raise LookupError("Clinic not found")
    if owner != tenant_id:
        raise CrossTenantViolationError("Clinic does not belong to the active tenant")


def clinic_scope_filter(model, clinic_id: UUID):
    """Return a SQLAlchemy clause constraining ``model`` to a clinic.

    Using this helper (instead of inlining ``Model.clinic_id == ...``)
    makes the isolation predicate grep-able across the codebase and
    gives one place to harden it later (e.g. tenant_id join).
    """
    return model.clinic_id == clinic_id


def all_in_clinic(ids: Iterable[UUID], expected_clinic_id: UUID) -> None:
    """Assert every id in ``ids`` equals ``expected_clinic_id``.

    For bulk writes that receive a list of clinic ids.
    """
    for cid in ids:
        if cid != expected_clinic_id:
            raise PermissionError("Cross-clinic access denied")
