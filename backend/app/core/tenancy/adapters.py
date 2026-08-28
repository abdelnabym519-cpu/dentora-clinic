"""SQLAlchemy adapters for the tenancy ports.

Implements the read :class:`~app.core.tenancy.ports.TenantGateway` and
the write :class:`~app.core.tenancy.provisioning.TenantProvisioner`.
These are the *only* places in core that know a tenant/clinic is stored
relationally; the use cases depend solely on the ports.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth.models import Clinic, ClinicMembership

from .models import Tenant
from .ports import ClinicMembershipRecord, TenantRecord
from .provisioning import TenantProvisioner


class SqlAlchemyTenantAdapter(TenantProvisioner):
    """Relational adapter backed by a request-scoped ``AsyncSession``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # --- TenantGateway (read) -------------------------------------------
    async def get_by_slug(self, slug: str) -> TenantRecord | None:
        result = await self._db.execute(select(Tenant).where(Tenant.slug == slug.lower()))
        return self._to_record(result.scalar_one_or_none())

    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None:
        result = await self._db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return self._to_record(result.scalar_one_or_none())

    async def list_active_tenants(self) -> list[TenantRecord]:
        result = await self._db.execute(
            select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.slug)
        )
        return [self._to_record(t) for t in result.scalars().all()]

    async def list_memberships(self, user_id: UUID) -> list[ClinicMembershipRecord]:
        result = await self._db.execute(
            select(ClinicMembership)
            .options(selectinload(ClinicMembership.clinic).selectinload(Clinic.tenant))
            .where(ClinicMembership.user_id == user_id)
        )
        records: list[ClinicMembershipRecord] = []
        for m in result.scalars().all():
            if m.clinic is None or m.clinic.tenant is None:
                # Defensive: a clinic without a tenant is a bootstrap
                # inconsistency and must never silently grant access.
                continue
            records.append(
                ClinicMembershipRecord(
                    clinic_id=m.clinic_id,
                    clinic_name=m.clinic.name,
                    tenant_id=m.clinic.tenant.id,
                    tenant_slug=m.clinic.tenant.slug,
                    role=m.role,
                    is_professional=bool(m.is_professional),
                    clinic_is_active=bool(m.clinic.is_active),
                )
            )
        return records

    # --- TenantProvisioner (write) --------------------------------------
    async def create_tenant(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        display_name: str,
        db_url: str | None,
        settings: dict,
    ) -> TenantRecord:
        tenant = Tenant(
            id=tenant_id,
            slug=slug,
            display_name=display_name,
            db_url=db_url,
            is_active=True,
            settings=dict(settings or {}),
        )
        self._db.add(tenant)
        await self._db.flush()
        return self._to_record(tenant)  # type: ignore[arg-type]

    async def create_clinic(
        self,
        *,
        clinic_id: UUID,
        tenant_id: UUID,
        name: str,
        tax_id: str,
        legal_name: str | None,
        timezone: str,
        currency: str,
        address: dict,
        phone: str | None,
        email: str | None,
        settings: dict,
    ) -> UUID:
        clinic = Clinic(
            id=clinic_id,
            tenant_id=tenant_id,
            name=name,
            tax_id=tax_id,
            legal_name=legal_name,
            timezone=timezone,
            currency=currency,
            address=dict(address or {}),
            phone=phone,
            email=email,
            settings=dict(settings or {}),
            is_active=True,
        )
        self._db.add(clinic)
        await self._db.flush()
        return clinic.id

    async def membership_exists(self, *, user_id: UUID, clinic_id: UUID) -> bool:
        result = await self._db.execute(
            select(ClinicMembership.id).where(
                ClinicMembership.user_id == user_id,
                ClinicMembership.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_membership(
        self,
        *,
        membership_id: UUID,
        user_id: UUID,
        clinic_id: UUID,
        role: str,
    ) -> None:
        self._db.add(
            ClinicMembership(
                id=membership_id,
                user_id=user_id,
                clinic_id=clinic_id,
                role=role,
            )
        )
        await self._db.flush()

    @staticmethod
    def _to_record(tenant: Tenant | None) -> TenantRecord | None:
        if tenant is None:
            return None
        return TenantRecord(
            id=tenant.id,
            slug=tenant.slug,
            display_name=tenant.display_name,
            is_active=bool(tenant.is_active),
            db_url=tenant.db_url,
            settings=dict(tenant.settings or {}),
        )
