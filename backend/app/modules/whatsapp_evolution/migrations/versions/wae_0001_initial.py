"""whatsapp_evolution: initial provider schema.

Tables live on their own Alembic branch so module uninstall/migration checks
remain isolated from Dentora core data.

Revision ID: wae_0001
Revises: 0001
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "wae_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("whatsapp_evolution",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_evolution_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("instance_name", sa.String(length=120), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("webhook_token_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("connection_state", sa.String(length=32), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_configured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("base_url", "instance_name", name="uq_whatsapp_evolution_instance"),
    )
    op.create_index(
        "idx_whatsapp_evolution_settings_clinic",
        "whatsapp_evolution_settings",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        "idx_whatsapp_evolution_settings_instance",
        "whatsapp_evolution_settings",
        ["instance_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_evolution_settings_clinic_id"),
        "whatsapp_evolution_settings",
        ["clinic_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_whatsapp_evolution_settings_instance_name"),
        "whatsapp_evolution_settings",
        ["instance_name"],
        unique=False,
    )

    op.create_table(
        "whatsapp_evolution_webhook_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clinic_id", "event_hash", name="uq_whatsapp_evolution_webhook_hash"
        ),
    )
    op.create_index(
        "idx_whatsapp_evolution_webhook_clinic",
        "whatsapp_evolution_webhook_receipts",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_whatsapp_evolution_webhook_receipts_clinic_id"),
        "whatsapp_evolution_webhook_receipts",
        ["clinic_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("whatsapp_evolution_webhook_receipts")
    op.drop_table("whatsapp_evolution_settings")
