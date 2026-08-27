"""Ports (interfaces) for the tenancy / multi-clinic bounded context.

These are *Dependency Inversion* seams: core use cases depend on these
abstract protocols, and a SQLAlchemy-backed adapter in
``app.core.tenancy.adapters`` implements them. Core never imports
SQLAlchemy session machinery into the use-case layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantRecord:
    """Immutable projection of a tenant returned by the gateway."""

    id: UUID
    slug: str
    display_name: str
    is_active: bool
    db_url: str | None
    settings: dict


@dataclass(frozen=True, slots=True)
class ClinicMembershipRecord:
    """Immutable projection of one (clinic, role) pair for a user."""

    clinic_id: UUID
    clinic_name: str
    tenant_id: UUID
    tenant_slug: str
    role: str
    is_professional: bool
    clinic_is_active: bool


@runtime_checkable
class TenantGateway(Protocol):
    """Read model for resolving tenants and a user's memberships.

    Implemented by the SQLAlchemy adapter. Use cases call only these
    methods, so they remain unit-testable without a database and a
    future SaaS control-plane adapter can substitute cleanly.
    """

    async def get_by_slug(self, slug: str) -> TenantRecord | None:
        """Return the active tenant with ``slug`` or ``None``."""
        ...

    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None:
        """Return the tenant with ``tenant_id`` or ``None``."""
        ...

    async def list_memberships(self, user_id: UUID) -> list[ClinicMembershipRecord]:
        """Return every (clinic, role) membership for ``user_id``."""
        ...

    async def list_active_tenants(self) -> list[TenantRecord]:
        """List active tenants (platform admin provisioning screens)."""
        ...
