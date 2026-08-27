"""Tenancy bootstrap.

Guarantees the invariant required by the multi-tenant layer:

* there is always a tenant row for ``settings.TENANT_SLUG`` (the
  self-hosted / default tenant), and
* every existing clinic is owned by that tenant.

Idempotent — running it on every startup (after migrations) is safe and
makes upgrading a pre-multi-tenant database a zero-downtime no-op: the
first run creates the tenant + backfills ``clinic.tenant_id``, later
runs find nothing to do.

The bootstrap runs inside its own short-lived session so it works in
both the API lifespan and the CLI / migration scripts without depending
on a request.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update

from app.config import settings
from app.database import async_session_maker

from .models import Tenant

logger = logging.getLogger(__name__)


async def ensure_default_tenant() -> str:
    """Create the default tenant and attach orphan clinics.

    Returns the default tenant slug. Safe to call repeatedly.
    """
    from app.core.auth.models import Clinic

    async with async_session_maker() as db:
        result = await db.execute(select(Tenant).where(Tenant.slug == settings.TENANT_SLUG))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                slug=settings.TENANT_SLUG,
                display_name="Default Tenant",
                is_active=True,
                settings={},
            )
            db.add(tenant)
            await db.flush()
            logger.info("Created default tenant %r (%s)", tenant.slug, tenant.id)

        # Backfill any clinics created before tenant_id existed.
        await db.execute(
            update(Clinic).where(Clinic.tenant_id.is_(None)).values(tenant_id=tenant.id)
        )
        await db.commit()
        return tenant.slug
