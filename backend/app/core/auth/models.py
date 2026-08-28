"""Core authentication and authorization models."""

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

from .permissions import PROFESSIONAL_ROLES

if TYPE_CHECKING:
    from app.core.tenancy.models import Tenant
    from app.modules.agenda.models import Appointment, Cabinet
    from app.modules.patients.models import Patient


# Well-known UUID of the bootstrap default tenant. Kept stable so tests,
# first-run setup and the alembic seed all agree without a lookup.
_DEFAULT_TENANT_UUID = UUID("00000000-0000-0000-0000-000000000001")


class Clinic(Base, TimestampMixin):
    """Clinic entity - the main organizational unit."""

    __tablename__ = "clinics"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str] = mapped_column(String(20))  # CIF/NIF
    legal_name: Mapped[str | None] = mapped_column(String(200), default=None)
    address: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    # IANA timezone id (e.g. "Europe/Madrid"). Single source of truth
    # for any module that needs local-time semantics — schedules,
    # reports, future billing date-windows, etc.
    # Soft-suspend a clinic (e.g. overdue billing). Authentication still
    # succeeds so the owner can see the status, but selecting the clinic
    # is rejected at the auth boundary. Defaults to true so existing
    # rows and self-hosted installs are unaffected.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/Madrid"
    )
    # ISO 4217 currency code. Single source of truth for any module
    # that renders money — budgets, invoices, catalog, reports.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Tenant that owns this clinic (multi-tenant / multi-clinic).
    # NOT NULL at the database level (enforced by migration 0007 after
    # backfill). The Python-side default attaches in-memory construction
    # to the well-known default tenant so legacy code paths and tests
    # that build a Clinic without an explicit tenant stay valid; real
    # provisioning always sets tenant_id explicitly. Every business row
    # is reachable only through a clinic owned by the request's tenant,
    # which gives repository-level defense in depth on top of the
    # per-request ``clinic_id`` filter.
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
        default=lambda: _DEFAULT_TENANT_UUID,
        server_default=text("'00000000-0000-0000-0000-000000000001'"),
    )

    # Relationships
    memberships: Mapped[list["ClinicMembership"]] = relationship(
        back_populates="clinic", cascade="all, delete-orphan"
    )
    tenant: Mapped["Tenant | None"] = relationship(back_populates="clinics")
    patients: Mapped[list["Patient"]] = relationship(back_populates="clinic")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="clinic")
    cabinets: Mapped[list["Cabinet"]] = relationship(
        back_populates="clinic",
        cascade="all, delete-orphan",
        order_by="Cabinet.display_order",
    )


class User(Base, TimestampMixin):
    """User account for authentication."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    professional_id: Mapped[str | None] = mapped_column(String(50))  # Colegiado number
    is_active: Mapped[bool] = mapped_column(default=True)
    # Platform (super) admin — operators of a multi-tenant Dentora
    # deployment who manage tenants/provisioning across the whole
    # platform. This is orthogonal to a clinic ``role``: a platform
    # admin has NO implicit access to a clinic's clinical data until
    # they explicitly select/impersonate a clinic (and that access is
    # audited). Self-hosted single-clinic installs simply leave it
    # false and the flag has no effect.
    is_platform_admin: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), nullable=False
    )
    token_version: Mapped[int] = mapped_column(default=0)  # For token revocation

    # Relationships
    memberships: Mapped[list["ClinicMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def _derive_is_professional(context) -> bool:  # noqa: ANN001 — SQLAlchemy ExecutionContext
    """Insert-time default: dentists/hygienists are professionals."""
    params = context.get_current_parameters()
    return params.get("role") in PROFESSIONAL_ROLES


class ClinicMembership(Base, TimestampMixin):
    """Association between users and clinics with role."""

    __tablename__ = "clinic_memberships"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    role: Mapped[str] = mapped_column(
        String(20)
    )  # admin, dentist, hygienist, assistant, receptionist
    # Whether this member appears in the agenda, holds working hours and
    # can be assigned treatments. Decoupled from ``role`` so an admin can
    # also practise (solo clinics) — professional-ness is a fact about
    # the person, the role is about permissions. When not set explicitly,
    # it derives from the role at insert time, so plain
    # ``ClinicMembership(role="dentist")`` keeps behaving as before.
    is_professional: Mapped[bool] = mapped_column(
        default=_derive_is_professional, server_default=text("false"), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="memberships")
    clinic: Mapped["Clinic"] = relationship(back_populates="memberships")
