"""dental_3d module — Phase 3 segmentation analyses.

Revision ID: d3d_0002
Revises: d3d_0001
Create Date: 2026-08-23

Stays on the isolated ``dental_3d`` Alembic branch (ADR 0002): module
uninstall downgrades only this chain. Append-only analysis history +
dentist review state; dropped wholesale on uninstall (analyses are
derivable decision support, not source clinical data — ADR 0021).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3d_0002"
down_revision: str | None = "d3d_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dental_segmentation_analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("performed_by", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("teeth", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_dental_segmentation_review_status",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dental_segmentation_analyses_clinic_id"),
        "dental_segmentation_analyses",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dental_segmentation_analyses_patient_id"),
        "dental_segmentation_analyses",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "idx_dental_segmentation_latest",
        "dental_segmentation_analyses",
        ["clinic_id", "patient_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_dental_segmentation_latest", table_name="dental_segmentation_analyses")
    op.drop_index(
        op.f("ix_dental_segmentation_analyses_patient_id"),
        table_name="dental_segmentation_analyses",
    )
    op.drop_index(
        op.f("ix_dental_segmentation_analyses_clinic_id"),
        table_name="dental_segmentation_analyses",
    )
    op.drop_table("dental_segmentation_analyses")
