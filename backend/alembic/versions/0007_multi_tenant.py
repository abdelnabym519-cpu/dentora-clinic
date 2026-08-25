"""core — multi-tenant / multi-clinic foundation.

Introduces the ``tenants`` table and links every existing clinic to the
bootstrap default tenant, plus two user/clinic flags needed by the
platform-admin and clinic-selection features:

* ``tenants`` — one row per deployment/account (slug, db_url, settings).
* ``clinics.tenant_id`` — ownership FK (nullable temporarily so the
  backfill can run), then made NOT NULL.
* ``clinics.is_active`` — soft-suspend a clinic.
* ``users.is_platform_admin`` — cross-tenant operator flag.

Self-hosted upgrades are a no-op after the first run: one default
tenant row is created and all clinics point at it. The migration is
fully reversible (downgrade drops the columns/table).

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from sqlalchemy import Boolean, Column, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Tenants table. We build columns explicitly (not via the Table
    #    helper above) so the timestamp columns match the ORM model.
    op.create_table(
        "tenants",
        Column("id", UUID(as_uuid=True), primary_key=True),
        Column("slug", String(64), nullable=False),
        Column("display_name", String(200), nullable=False),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("db_url", String(1024), nullable=True),
        Column("settings", JSONB, nullable=False, server_default=text("'{}'")),
        Column("created_at", String(64), nullable=True),
        Column("updated_at", String(64), nullable=True),
    )
    # The primary key already provides an index on tenants.id; only the
    # unique slug lookup needs an explicit index.
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # Timestamp columns should be timezone-aware; fix their type now
    # (declared as placeholders above to keep the create_table simple).
    op.execute("ALTER TABLE tenants ALTER COLUMN created_at TYPE timestamptz USING now()")
    op.execute("ALTER TABLE tenants ALTER COLUMN updated_at TYPE timestamptz USING now()")
    op.execute("ALTER TABLE tenants ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE tenants ALTER COLUMN updated_at SET NOT NULL")

    # 2) New columns on clinics / users.
    op.add_column(
        "clinics",
        Column(
            "tenant_id",
            UUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_clinics_tenant_id", "clinics", ["tenant_id"])
    op.add_column(
        "clinics",
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
    )
    op.add_column(
        "users",
        Column(
            "is_platform_admin",
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )

    # 3) Seed the default tenant (deterministic UUID) and attach clinics.
    default_tenant_id = "00000000-0000-0000-0000-000000000001"
    bind.execute(
        text(
            "INSERT INTO tenants (id, slug, display_name, is_active, settings, "
            "created_at, updated_at) VALUES (:id, 'default', 'Default Tenant', true, "
            "'{}'::jsonb, now(), now()) ON CONFLICT (slug) DO NOTHING"
        ),
        {"id": default_tenant_id},
    )
    bind.execute(
        text("UPDATE clinics SET tenant_id = :tid WHERE tenant_id IS NULL"),
        {"tid": default_tenant_id},
    )

    # 4) Enforce NOT NULL now that every clinic has an owner.
    op.alter_column("clinics", "tenant_id", nullable=False)


def downgrade() -> None:
    op.alter_column("clinics", "tenant_id", nullable=True)
    op.drop_column("users", "is_platform_admin")
    op.drop_column("clinics", "is_active")
    op.drop_index("ix_clinics_tenant_id", table_name="clinics")
    op.drop_column("clinics", "tenant_id")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
