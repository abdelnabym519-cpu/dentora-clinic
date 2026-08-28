"""dental_3d patient-specific IOS to CBCT rigid registration.

Revision ID: d3d_0005
Revises: d3d_0004
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3d_0005"
down_revision: str | None = "d3d_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dental_alignment_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("algorithm", sa.String(length=100), nullable=False),
        sa.Column("algorithm_version", sa.String(length=255), nullable=False),
        sa.Column("transform", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_frame", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("target_frame", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column("failure_message", sa.String(length=255), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'accepted', 'rejected', 'failed', 'uncertain')",
            name="ck_dental_alignment_status",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dental_alignment_results_clinic_id",
        "dental_alignment_results",
        ["clinic_id"],
    )
    op.create_index(
        "ix_dental_alignment_results_patient_id",
        "dental_alignment_results",
        ["patient_id"],
    )
    op.create_index(
        "idx_dental_alignment_latest",
        "dental_alignment_results",
        ["clinic_id", "patient_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_dental_alignment_latest", table_name="dental_alignment_results")
    op.drop_index("ix_dental_alignment_results_patient_id", table_name="dental_alignment_results")
    op.drop_index("ix_dental_alignment_results_clinic_id", table_name="dental_alignment_results")
    op.drop_table("dental_alignment_results")
