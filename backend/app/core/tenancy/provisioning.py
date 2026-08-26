"""Provisioning use cases for the tenancy context.

These are the *application* / use-case layer of Clean Architecture:
they orchestrate creating tenants and clinics, depend only on the
abstract ports in :mod:`app.core.tenancy.ports`, and know nothing about
FastAPI, SQLAlchemy sessions or HTTP. The SQLAlchemy adapter implements
:class:`TenantProvisioner` and the routers/CLI call these use cases.

Naming follows Screaming Architecture — the module announces the
business intent (``provision_tenant``, ``provision_clinic``) rather
than the framework it runs on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from .ports import TenantRecord

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class TenantProvisioningError(ValueError):
    """Raised when provisioning input is invalid or conflicts with state.

    A domain-level error (not HTTP). The interface adapter (router/CLI)
    translates it into the appropriate status code.
    """


@dataclass(frozen=True, slots=True)
class ProvisionTenantCommand:
    slug: str
    display_name: str
    owner_user_id: UUID | None = None
    db_url: str | None = None
    settings: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProvisionClinicCommand:
    tenant_id: UUID
    name: str
    tax_id: str
    legal_name: str | None = None
    timezone: str = "Europe/Madrid"
    currency: str = "EUR"
    address: dict | None = None
    phone: str | None = None
    email: str | None = None
    settings: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProvisionMembershipCommand:
    user_id: UUID
    clinic_id: UUID
    role: str


class ProvisionTenant:
    """Create a new tenant (platform-admin / self-hosted bootstrap)."""

    def __init__(self, gateway: TenantProvisioner) -> None:
        self._gateway = gateway

    async def execute(self, command: ProvisionTenantCommand) -> TenantRecord:
        slug = command.slug.strip().lower()
        if not _SLUG_RE.match(slug):
            raise TenantProvisioningError(
                "Invalid tenant slug: use 2–63 lowercase letters, digits "
                "or hyphens, must not start/end with a hyphen."
            )
        if not command.display_name.strip():
            raise TenantProvisioningError("Tenant display name is required")
        existing = await self._gateway.get_by_slug(slug)
        if existing is not None:
            raise TenantProvisioningError(f"Tenant slug already exists: {slug!r}")
        return await self._gateway.create_tenant(
            tenant_id=uuid4(),
            slug=slug,
            display_name=command.display_name.strip(),
            db_url=command.db_url,
            settings=command.settings or {},
        )


class ProvisionClinic:
    """Create a new clinic within a tenant."""

    def __init__(self, gateway: TenantProvisioner) -> None:
        self._gateway = gateway

    async def execute(self, command: ProvisionClinicCommand) -> UUID:
        if not command.name.strip():
            raise TenantProvisioningError("Clinic name is required")
        if not command.tax_id.strip():
            raise TenantProvisioningError("Clinic tax id is required")
        if len(command.currency) != 3 or not command.currency.isalpha():
            raise TenantProvisioningError("Currency must be a 3-letter ISO code")
        tenant = await self._gateway.get_by_id(command.tenant_id)
        if tenant is None:
            raise TenantProvisioningError("Unknown tenant")
        if not tenant.is_active:
            raise TenantProvisioningError("Cannot provision a clinic in a suspended tenant")
        return await self._gateway.create_clinic(
            clinic_id=uuid4(),
            tenant_id=command.tenant_id,
            name=command.name.strip(),
            tax_id=command.tax_id.strip(),
            legal_name=command.legal_name,
            timezone=command.timezone,
            currency=command.currency.upper(),
            address=command.address or {},
            phone=command.phone,
            email=command.email,
            settings=command.settings or {},
        )


class AssignMembership:
    """Attach a user to a clinic with a role."""

    _VALID_ROLES = ("admin", "dentist", "hygienist", "assistant", "receptionist")

    def __init__(self, gateway: TenantProvisioner) -> None:
        self._gateway = gateway

    async def execute(self, command: ProvisionMembershipCommand) -> None:
        if command.role not in self._VALID_ROLES:
            raise TenantProvisioningError(
                f"Invalid role {command.role!r}; expected one of {self._VALID_ROLES}"
            )
        if await self._gateway.membership_exists(
            user_id=command.user_id, clinic_id=command.clinic_id
        ):
            raise TenantProvisioningError("User already belongs to this clinic")
        await self._gateway.create_membership(
            membership_id=uuid4(),
            user_id=command.user_id,
            clinic_id=command.clinic_id,
            role=command.role,
        )


class TenantProvisioner:  # pragma: no cover - interface declaration
    """Write-side port implemented by the SQLAlchemy adapter.

    Declared as an abstract base (rather than a ``Protocol``) so use
    cases can ``isinstance``-check in tests and the adapter clearly
    advertises the contract it must fulfill.
    """

    async def get_by_slug(self, slug: str) -> TenantRecord | None: ...
    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None: ...
    async def create_tenant(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        display_name: str,
        db_url: str | None,
        settings: dict,
    ) -> TenantRecord: ...
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
    ) -> UUID: ...
    async def membership_exists(self, *, user_id: UUID, clinic_id: UUID) -> bool: ...
    async def create_membership(
        self,
        *,
        membership_id: UUID,
        user_id: UUID,
        clinic_id: UUID,
        role: str,
    ) -> None: ...
