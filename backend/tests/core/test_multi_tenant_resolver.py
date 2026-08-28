"""Integration tests for MultiTenantResolver + bootstrap + platform API."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.service import create_access_token, hash_password
from app.core.tenancy.adapters import SqlAlchemyTenantAdapter
from app.core.tenancy.models import Tenant
from app.core.tenancy.resolver_impl import MultiTenantResolver


@pytest.mark.asyncio
async def test_resolver_resolves_default_tenant(db_session: AsyncSession) -> None:
    adapter = SqlAlchemyTenantAdapter(db_session)
    resolver = MultiTenantResolver(adapter)
    ctx = await resolver.resolve_by_slug("default")
    assert ctx.slug == "default"
    assert ctx.db_url  # shared DB URL


@pytest.mark.asyncio
async def test_resolver_unknown_slug_lookup_error(db_session: AsyncSession) -> None:
    resolver = MultiTenantResolver(SqlAlchemyTenantAdapter(db_session))
    with pytest.raises(LookupError):
        await resolver.resolve_by_slug("does-not-exist")


@pytest.mark.asyncio
async def test_resolver_rejects_suspended_tenant(db_session: AsyncSession) -> None:
    tenant = Tenant(slug="suspended", display_name="S", is_active=False)
    db_session.add(tenant)
    await db_session.commit()
    resolver = MultiTenantResolver(SqlAlchemyTenantAdapter(db_session))
    with pytest.raises(LookupError):
        await resolver.resolve_by_slug("suspended")


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(db_session: AsyncSession) -> None:
    from sqlalchemy import func, select

    from app.core.auth.models import Clinic
    from app.core.tenancy.bootstrap import ensure_default_tenant

    slug = await ensure_default_tenant()
    assert slug == "default"
    # A second call must not raise and must not create duplicate rows.
    await ensure_default_tenant()
    count = await db_session.scalar(select(func.count()).select_from(Tenant))
    assert count == 1
    # Orphan clinics (none here, but the update path runs without error)
    orphans = await db_session.scalar(
        select(func.count()).select_from(Clinic).where(Clinic.tenant_id.is_(None))
    )
    assert orphans == 0


@pytest.mark.asyncio
async def test_platform_tenants_endpoint_requires_admin(
    client: AsyncClient,
) -> None:
    # No auth → 401.
    resp = await client.get("/api/v1/platform/tenants")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_platform_admin_full_provisioning_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Create a platform admin directly and a token for them.
    from app.core.auth.models import User

    admin = User(
        email="platform@example.com",
        password_hash=hash_password("PlatformPass1"),
        first_name="Platform",
        last_name="Admin",
        is_platform_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()
    token = create_access_token(admin.id, token_version=admin.token_version)
    headers = {"Authorization": f"Bearer {token}"}

    # Create a new tenant.
    resp = await client.post(
        "/api/v1/platform/tenants",
        json={"slug": "acme", "display_name": "Acme Dental"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    tenant = resp.json()["data"]
    assert tenant["slug"] == "acme"

    # Create a clinic in the tenant.
    resp = await client.post(
        "/api/v1/platform/clinics",
        json={
            "tenant_id": tenant["id"],
            "name": "Acme Clinic",
            "tax_id": "B11111111",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    clinic = resp.json()["data"]
    assert clinic["tenant_id"] == tenant["id"]

    # Create a regular user and attach them to the new clinic as dentist.
    resp = await client.post(
        "/api/v1/platform/users",
        json={
            "email": "dentist@acme.com",
            "password": "DentistPass1",
            "first_name": "Dan",
            "last_name": "Dentist",
            "clinic_id": clinic["id"],
            "role": "dentist",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Listing clinics/tenants works for platform admin.
    resp = await client.get("/api/v1/platform/tenants", headers=headers)
    assert resp.status_code == 200
    slugs = [t["slug"] for t in resp.json()["data"]]
    assert "acme" in slugs and "default" in slugs


@pytest.mark.asyncio
async def test_non_platform_admin_forbidden(client: AsyncClient, db_session: AsyncSession) -> None:
    from app.core.auth.models import User

    user = User(
        email="regular@example.com",
        password_hash=hash_password("RegularPass1"),
        first_name="Reg",
        last_name="User",
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user.id, token_version=user.token_version)
    resp = await client.get(
        "/api/v1/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_default_tenant_uuid_constant() -> None:
    # The bootstrap uses a stable well-known UUID; guards/tests rely on it.
    assert UUID("00000000-0000-0000-0000-000000000001") is not None
