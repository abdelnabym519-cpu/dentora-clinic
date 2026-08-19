"""booking: durable cloud request receipts.

Revision ID: bk_0002
Revises: bk_0001
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bk_0002"
down_revision: str | None = "bk_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    id_column = sa.Column(
        "id",
        sa.UUID(),
        nullable=False,
    )
    clinic_id_column = sa.Column(
        "clinic_id",
        sa.UUID(),
        nullable=False,
    )
    request_id_column = sa.Column(
        "request_id",
        sa.String(length=128),
        nullable=False,
    )
    status_column = sa.Column(
        "status",
        sa.String(length=20),
        server_default=sa.text("'processing'"),
        nullable=False,
    )
    appointment_id_column = sa.Column(
        "appointment_id",
        sa.UUID(),
        nullable=True,
    )
    rejection_code_column = sa.Column(
        "rejection_code",
        sa.String(length=100),
        nullable=True,
    )
    created_at_column = sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
    )
    updated_at_column = sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
    )

    op.create_table(
        "booking_cloud_requests",
        id_column,
        clinic_id_column,
        request_id_column,
        status_column,
        appointment_id_column,
        rejection_code_column,
        created_at_column,
        updated_at_column,
        sa.ForeignKeyConstraint(
            [clinic_id_column],
            ["clinics.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [appointment_id_column],
            ["appointments.id"],
        ),
        sa.PrimaryKeyConstraint(
            id_column,
        ),
        sa.UniqueConstraint(
            clinic_id_column,
            request_id_column,
            name="uq_booking_cloud_requests_clinic_request",
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'accepted', 'rejected')",
            name="ck_booking_cloud_requests_status",
        ),
        sa.CheckConstraint(
            """
            (
                status = 'processing'
                AND appointment_id IS NULL
                AND rejection_code IS NULL
            )
            OR
            (
                status = 'accepted'
                AND appointment_id IS NOT NULL
                AND rejection_code IS NULL
            )
            OR
            (
                status = 'rejected'
                AND appointment_id IS NULL
                AND rejection_code IS NOT NULL
            )
            """,
            name="ck_booking_cloud_requests_result_shape",
        ),
    )


def downgrade() -> None:
    op.drop_table("booking_cloud_requests")
