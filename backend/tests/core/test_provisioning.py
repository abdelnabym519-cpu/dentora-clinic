"""Unit tests for provisioning use cases with an in-memory fake adapter."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.core.tenancy.ports import TenantRecord
from app.core.tenancy.provisioning import (
    AssignMembership,
    ProvisionClinic,
    ProvisionClinicCommand,
    ProvisionMembershipCommand,
    ProvisionTenant,
    ProvisionTenantCommand,
    TenantProvisioner,
    TenantProvisioningError,
)


class FakeTenantAdapter(TenantProvisioner):
    def __init__(self) -> None:
        self.tenants: dict[UUID, TenantRecord] = {}
        self.clinics: dict[UUID, dict] = {}
        self.memberships: set[tuple[UUID, UUID]] = set()

    async def get_by_slug(self, slug: str) -> TenantRecord | None:
        return next((t for t in self.tenants.values() if t.slug == slug), None)

    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None:
        return self.tenants.get(tenant_id)

    async def create_tenant(self, *, tenant_id, slug, display_name, db_url, settings):
        record = TenantRecord(
            id=tenant_id,
            slug=slug,
            display_name=display_name,
            is_active=True,
            db_url=db_url,
            settings=dict(settings),
        )
        self.tenants[tenant_id] = record
        return record

    async def create_clinic(self, *, clinic_id, tenant_id, **kwargs):
        self.clinics[clinic_id] = {"tenant_id": tenant_id, **kwargs}
        return clinic_id

    async def membership_exists(self, *, user_id, clinic_id):
        return (user_id, clinic_id) in self.memberships

    async def create_membership(self, *, membership_id, user_id, clinic_id, role):
        self.memberships.add((user_id, clinic_id))

    async def list_memberships(self, user_id):  # pragma: no cover - unused here
        return []

    async def list_active_tenants(self):  # pragma: no cover - unused here
        return [t for t in self.tenants.values() if t.is_active]


@pytest.mark.asyncio
async def test_provision_tenant_validates_slug() -> None:
    adapter = FakeTenantAdapter()
    with pytest.raises(TenantProvisioningError):
        await ProvisionTenant(adapter).execute(
            ProvisionTenantCommand(slug="BAD SLUG!", display_name="X")
        )


@pytest.mark.asyncio
async def test_provision_tenant_rejects_duplicate_slug() -> None:
    adapter = FakeTenantAdapter()
    cmd = ProvisionTenantCommand(slug="acme", display_name="Acme")
    await ProvisionTenant(adapter).execute(cmd)
    with pytest.raises(TenantProvisioningError):
        await ProvisionTenant(adapter).execute(cmd)


@pytest.mark.asyncio
async def test_provision_clinic_requires_tenant() -> None:
    adapter = FakeTenantAdapter()
    with pytest.raises(TenantProvisioningError):
        await ProvisionClinic(adapter).execute(
            ProvisionClinicCommand(tenant_id=uuid4(), name="C", tax_id="B1", currency="EUR")
        )


@pytest.mark.asyncio
async def test_provision_clinic_validates_currency() -> None:
    adapter = FakeTenantAdapter()
    tenant = await ProvisionTenant(adapter).execute(
        ProvisionTenantCommand(slug="acme", display_name="Acme")
    )
    with pytest.raises(TenantProvisioningError):
        await ProvisionClinic(adapter).execute(
            ProvisionClinicCommand(tenant_id=tenant.id, name="C", tax_id="B1", currency="euros")
        )


@pytest.mark.asyncio
async def test_provision_clinic_and_membership_happy_path() -> None:
    adapter = FakeTenantAdapter()
    tenant = await ProvisionTenant(adapter).execute(
        ProvisionTenantCommand(slug="acme", display_name="Acme")
    )
    clinic_id = await ProvisionClinic(adapter).execute(
        ProvisionClinicCommand(tenant_id=tenant.id, name="Main", tax_id="B1")
    )
    assert clinic_id in adapter.clinics
    user_id = uuid4()
    await AssignMembership(adapter).execute(
        ProvisionMembershipCommand(user_id=user_id, clinic_id=clinic_id, role="dentist")
    )
    assert (user_id, clinic_id) in adapter.memberships


@pytest.mark.asyncio
async def test_assign_membership_rejects_bad_role_and_duplicate() -> None:
    adapter = FakeTenantAdapter()
    tenant = await ProvisionTenant(adapter).execute(
        ProvisionTenantCommand(slug="acme", display_name="Acme")
    )
    clinic_id = await ProvisionClinic(adapter).execute(
        ProvisionClinicCommand(tenant_id=tenant.id, name="Main", tax_id="B1")
    )
    user_id = uuid4()
    cmd = ProvisionMembershipCommand(user_id=user_id, clinic_id=clinic_id, role="root")
    with pytest.raises(TenantProvisioningError):
        await AssignMembership(adapter).execute(cmd)
    await AssignMembership(adapter).execute(
        ProvisionMembershipCommand(user_id=user_id, clinic_id=clinic_id, role="admin")
    )
    with pytest.raises(TenantProvisioningError):
        await AssignMembership(adapter).execute(
            ProvisionMembershipCommand(user_id=user_id, clinic_id=clinic_id, role="admin")
        )
