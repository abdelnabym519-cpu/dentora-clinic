"""Real multi-tenant resolver.

Resolves a :class:`~app.core.tenancy.context.TenantContext` for every
HTTP request, background job and CLI call. In shared-PostgreSQL mode it
looks the tenant up by slug (host / header / JWT), verifies it is
active, and returns a context whose ``db_url`` points at the shared
database — identical runtime behaviour to the legacy
:class:`SingleTenantResolver` for self-hosted installs, which seed a
single ``"default"`` tenant.

It also publishes ``tenant.resolved`` on the event bus so auditors /
billing subscribers can react without the resolver knowing about them.

The resolver depends on the abstract
:class:`~app.core.tenancy.ports.TenantGateway` — it never opens a
session itself, which keeps it unit-testable and lets a future SaaS
control-plane adapter substitute cleanly.
"""

from __future__ import annotations

import logging
from uuid import UUID

from starlette.requests import Request

from app.config import settings
from app.core.plugins.registry import module_registry

from .context import TenantContext
from .ports import TenantGateway
from .selection import TenantHints, TenantResolutionError, resolve_tenant_slug

logger = logging.getLogger(__name__)


def _host_to_slug(host: str | None) -> str | None:
    """Derive a tenant slug from a virtual host (``acme.dentora.app``)."""
    if not host:
        return None
    # Strip port.
    host = host.split(":", 1)[0].lower().strip()
    if "." not in host:
        return None
    # The first label is the tenant slug in a wildcard deployment.
    candidate = host.split(".", 1)[0]
    return candidate or None


class MultiTenantResolver:
    """Database-backed tenant resolution for multi-tenant deployments."""

    def __init__(self, gateway: TenantGateway) -> None:
        self._gateway = gateway
        self._modules_enabled = frozenset(module.name for module in module_registry.list_modules())

    def _hints_from_request(self, request: Request) -> TenantHints:
        header = request.headers.get(settings.TENANT_HEADER)
        header_id: UUID | None = None
        if header:
            try:
                header_id = UUID(header)
            except (ValueError, AttributeError):
                # Not a UUID — treat it as a slug.
                pass
        jwt_slug: str | None = None
        # The auth middleware decodes the JWT and may stash the resolved
        # tenant slug on request.state (set by auth dependency).
        jwt_slug = getattr(request.state, "tenant_slug", None)
        return TenantHints(
            header_slug=None if header_id is not None else (header or None),
            header_tenant_id=header_id,
            host_slug=_host_to_slug(request.headers.get("host")),
            jwt_tenant_slug=jwt_slug,
            default_slug=settings.TENANT_SLUG,
            allow_default_fallback=settings.TENANT_DEFAULT_FALLBACK,
        )

    async def resolve(self, request: Request) -> TenantContext:
        hints = self._hints_from_request(request)
        try:
            slug = resolve_tenant_slug(hints)
        except TenantResolutionError as exc:
            raise LookupError(str(exc)) from exc

        if hints.header_tenant_id is not None:
            record = await self._gateway.get_by_id(hints.header_tenant_id)
            if record is not None and record.slug != slug and slug != settings.TENANT_SLUG:
                # Mismatch between header id and slug — do not guess.
                raise LookupError("Ambiguous tenant selection")
        else:
            record = await self._gateway.get_by_slug(slug)

        if record is None:
            raise LookupError(f"Unknown tenant: {slug!r}")
        if not record.is_active:
            raise LookupError(f"Tenant suspended: {slug!r}")

        return await self._to_context(record.slug, record.db_url)

    async def resolve_by_slug(self, slug: str) -> TenantContext:
        record = await self._gateway.get_by_slug(slug.lower())
        if record is None:
            raise LookupError(f"Unknown tenant slug: {slug!r}")
        if not record.is_active:
            raise LookupError(f"Tenant suspended: {slug!r}")
        return await self._to_context(record.slug, record.db_url)

    async def _to_context(self, slug: str, db_url: str | None) -> TenantContext:
        # In shared-PostgreSQL mode every tenant uses the app DB URL.
        # When a tenant row carries an explicit ``db_url`` (future
        # dedicated-database deployments), the engine registry routes it.
        effective_db_url = db_url or settings.DATABASE_URL
        ctx = TenantContext(
            slug=slug,
            db_url=effective_db_url,
            storage_prefix="" if slug == settings.TENANT_SLUG else f"tenants/{slug}/",
            modules_enabled=self._modules_enabled,
        )
        # Publish asynchronously-safe event. The bus runs handlers inline;
        # we import lazily to avoid a circular import at module load.
        try:
            from app.core.events.bus import event_bus
            from app.core.events.types import EventType

            await event_bus.publish(EventType.TENANT_RESOLVED, {"tenant_slug": slug})
        except Exception:  # noqa: BLE001 - resolution must never break on audit
            logger.debug("tenant.resolved publish failed", exc_info=True)
        return ctx
