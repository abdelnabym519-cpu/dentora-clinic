"""Tenant + clinic selection use cases.

Pure domain logic for deciding *which* tenant and *which* clinic a
request operates on, given:

* request hints (host, ``X-Tenant-Id`` / ``X-Clinic-Id`` headers, JWT),
* the authenticated user's memberships,
* deployment settings (self-hosted default fallback).

The logic here has **no** FastAPI or SQLAlchemy dependency — the
infrastructure layer (``resolver`` + auth dependency) collects the
hints, calls these functions/objects, and maps domain errors to HTTP.
This keeps the security-critical selection rules unit-testable in
isolation and reusable by background jobs and CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .ports import ClinicMembershipRecord


class TenantResolutionError(LookupError):
    """Raised when a tenant cannot be resolved from the supplied hints."""


class ClinicSelectionError(PermissionError):
    """Raised when a user may not select the requested clinic."""


@dataclass(frozen=True, slots=True)
class TenantHints:
    """Normalized hints collected from an HTTP request / job / CLI."""

    header_slug: str | None = None
    header_tenant_id: UUID | None = None
    host_slug: str | None = None
    jwt_tenant_slug: str | None = None
    # The deployment's own slug ("default" in self-hosted).
    default_slug: str = "default"
    # Whether the default slug may be used when no hint matches.
    allow_default_fallback: bool = True

    def candidate_slugs(self) -> list[str]:
        """Ordered candidate slugs, most specific first, de-duplicated."""
        seen: set[str] = set()
        ordered: list[str] = []
        for value in (self.header_slug, self.host_slug, self.jwt_tenant_slug):
            if value and value not in seen:
                seen.add(value)
                ordered.append(value.lower())
        return ordered


def resolve_tenant_slug(hints: TenantHints) -> str:
    """Pick the tenant slug for a request.

    Explicit hints win; otherwise fall back to the deployment default
    when allowed. Raises :class:`TenantResolutionError` if nothing
    matches and fallback is disabled (strict SaaS mode).
    """
    for slug in hints.candidate_slugs():
        return slug
    if hints.allow_default_fallback:
        return hints.default_slug
    raise TenantResolutionError("No tenant could be resolved from the request")


@dataclass(frozen=True, slots=True)
class SelectedClinic:
    """The outcome of clinic selection: membership + tenant provenance."""

    clinic_id: UUID
    tenant_id: UUID
    tenant_slug: str
    role: str
    is_professional: bool


def select_clinic(
    memberships: list[ClinicMembershipRecord],
    *,
    requested_clinic_id: UUID | None,
    requested_tenant_id: UUID | None = None,
) -> SelectedClinic:
    """Select the effective clinic for an authenticated user.

    * When ``requested_clinic_id`` is supplied, the user MUST hold a
      membership for it (and, if a tenant is also pinned, it MUST belong
      to that tenant) — otherwise 403.
    * When not supplied, the membership is chosen deterministically
      (sorted by clinic name) so multi-clinic users get a stable default
      they can then override via the header.
    """
    if not memberships:
        raise ClinicSelectionError("User is not a member of any clinic")

    if requested_clinic_id is not None:
        match = next(
            (m for m in memberships if m.clinic_id == requested_clinic_id),
            None,
        )
        if match is None:
            raise ClinicSelectionError("User does not have access to the requested clinic")
        if requested_tenant_id is not None and match.tenant_id != requested_tenant_id:
            raise ClinicSelectionError("Requested clinic does not belong to the active tenant")
        if not match.clinic_is_active:
            raise ClinicSelectionError("Requested clinic is suspended")
        return SelectedClinic(
            clinic_id=match.clinic_id,
            tenant_id=match.tenant_id,
            tenant_slug=match.tenant_slug,
            role=match.role,
            is_professional=match.is_professional,
        )

    candidates = sorted(
        (m for m in memberships if m.clinic_is_active),
        key=lambda m: (m.clinic_name.lower(), str(m.clinic_id)),
    )
    if not candidates:
        raise ClinicSelectionError("User has no active clinic")
    chosen = candidates[0]
    return SelectedClinic(
        clinic_id=chosen.clinic_id,
        tenant_id=chosen.tenant_id,
        tenant_slug=chosen.tenant_slug,
        role=chosen.role,
        is_professional=chosen.is_professional,
    )
