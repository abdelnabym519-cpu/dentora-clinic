"""Persistence model for a *tenant*.

A tenant is the top-level isolation + billing unit of a Dentora
deployment. In a self-hosted install there is exactly one row
(``slug == settings.TENANT_SLUG``, default ``"default"``). In a shared
SaaS deployment there are N rows, one per paying account.

A tenant owns one or many :class:`~app.core.auth.models.Clinic` rows.
Cross-clinic row isolation is still enforced by ``clinic_id`` on every
business table; ``tenant_id`` on ``clinics`` is the *defense in depth*
anchor — every clinic-scoped row is provably reachable only through a
clinic owned by the request's tenant.

This module deliberately imports nothing from ``app.modules`` so it can
be imported from anywhere (alembic env, CLI, tests) without pulling in
the module graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic


class Tenant(Base, TimestampMixin):
    """A deployment / subscription / database-isolation unit."""

    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Human-stable identifier used in hosts, headers and the resolver.
    # Globally unique and lowercase by convention.
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # When false the tenant is suspended (billing / compliance) and every
    # authenticated request to it is rejected at the resolver boundary.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Optional *override* database URL for this tenant. When ``None`` the
    # shared :data:`app.database.engine` (``settings.DATABASE_URL``) is
    # used. Populating this for a row is the seam that lets a future
    # dedicated-database-per-tenant deployment route a single tenant to
    # its own cluster **without** a code change — the engine registry
    # already keys by URL.
    db_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Opaque per-tenant settings: plan, storage prefix, feature flags,
    # support contact, etc. Core reads only the keys it owns; the SaaS
    # module is free to add its own.
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))

    clinics: Mapped[list[Clinic]] = relationship(
        back_populates="tenant",
        cascade="save-update, merge",
    )
