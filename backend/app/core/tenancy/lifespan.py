"""Wiring helpers for the tenant resolver and engine registry.

Kept out of ``app.main`` so the bootstrap can also be invoked from the
CLI and tests without importing the whole FastAPI app.
"""

from __future__ import annotations

import logging
from typing import cast

from app.database import async_session_maker, engine

from .adapters import SqlAlchemyTenantAdapter
from .context import TenantContext
from .engines import TenantEngineRegistry
from .ports import TenantGateway
from .resolver_impl import MultiTenantResolver

logger = logging.getLogger(__name__)


class SessionBackedTenantGateway(TenantGateway):
    """A gateway that opens its own short-lived session per call.

    Used by the HTTP-level resolver, which runs before the request's
    ``get_db`` dependency has produced a session. Routers that already
    hold a session should construct a :class:`SqlAlchemyTenantAdapter`
    directly instead.
    """

    async def get_by_slug(self, slug: str):  # type: ignore[override]
        async with async_session_maker() as db:
            return await SqlAlchemyTenantAdapter(db).get_by_slug(slug)

    async def get_by_id(self, tenant_id):  # type: ignore[override]
        async with async_session_maker() as db:
            return await SqlAlchemyTenantAdapter(db).get_by_id(tenant_id)

    async def list_memberships(self, user_id):  # type: ignore[override]
        async with async_session_maker() as db:
            return await SqlAlchemyTenantAdapter(db).list_memberships(user_id)

    async def list_active_tenants(self):  # type: ignore[override]
        async with async_session_maker() as db:
            return await SqlAlchemyTenantAdapter(db).list_active_tenants()


def build_resolver() -> MultiTenantResolver:
    """Construct the production multi-tenant resolver."""
    return MultiTenantResolver(cast(TenantGateway, SessionBackedTenantGateway()))


def build_engine_registry() -> TenantEngineRegistry:
    return TenantEngineRegistry(engine)


async def resolve_default_context(resolver: MultiTenantResolver) -> TenantContext:
    """Resolve the default tenant (jobs / CLI / startup)."""
    from app.config import settings

    return await resolver.resolve_by_slug(settings.TENANT_SLUG)
