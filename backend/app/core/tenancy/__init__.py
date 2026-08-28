"""Tenant context, resolution and multi-clinic foundation.

See ``docs/technical/multi-tenancy.md`` for the architectural overview.

Public surface:

* :class:`TenantContext` — immutable description of the active tenant.
* :class:`TenantResolver` — the resolution Protocol.
* :class:`SingleTenantResolver` — self-hosted, always-``"default"``.
* :class:`MultiTenantResolver` — shared-PostgreSQL multi-tenant resolver.
* :class:`Tenant` — persistence model for tenants.
* Provisioning + selection use cases and SQLAlchemy adapters live in
  :mod:`app.core.tenancy.provisioning`,
  :mod:`app.core.tenancy.selection` and
  :mod:`app.core.tenancy.adapters`.
"""

from .context import TenantContext
from .models import Tenant
from .resolver import TenantResolver
from .resolver_impl import MultiTenantResolver
from .single import DEFAULT_TENANT_SLUG, SingleTenantResolver

__all__ = [
    "DEFAULT_TENANT_SLUG",
    "MultiTenantResolver",
    "SingleTenantResolver",
    "Tenant",
    "TenantContext",
    "TenantResolver",
]
