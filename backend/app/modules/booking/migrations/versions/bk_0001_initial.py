"""booking: initial public booking settings.

Revision ID: bk_0001
Revises: 0001
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bk_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("booking",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("public_slug", sa.String(length=120), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "slot_minutes",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column(
            "days_ahead",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "slot_minutes >= 5 AND slot_minutes <= 240",
            name="ck_booking_settings_slot_minutes",
        ),
        sa.CheckConstraint(
            "days_ahead >= 1 AND days_ahead <= 180",
            name="ck_booking_settings_days_ahead",
        ),
    )

    op.create_index(
        "ix_booking_settings_clinic_id",
        "booking_settings",
        ["clinic_id"],
        unique=True,
    )

    op.create_index(
        "ix_booking_settings_public_slug",
        "booking_settings",
        ["public_slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_booking_settings_public_slug",
        table_name="booking_settings",
    )
    op.drop_index(
        "ix_booking_settings_clinic_id",
        table_name="booking_settings",
    )
    op.drop_table("booking_settings")
