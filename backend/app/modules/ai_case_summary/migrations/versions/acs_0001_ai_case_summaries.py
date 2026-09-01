"""AI Case Summary persistence and dentist review state.

Revision ID: acs_0001
Revises: 0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "acs_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("ai_case_summary",)
# ai_case_summaries.patient_id FKs patients, created by ``pat_0001`` on the
# main chain. Without this edge alembic may run acs_0001 (branched off 0001)
# before pat_0001 on a clean upgrade, so the FK target doesn't exist yet.
# depends_on forces the correct order (same pattern as cop_0001).
depends_on: str | Sequence[str] | None = "pat_0001"


def upgrade() -> None:
    op.create_table(
        "ai_case_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("case_snapshot_contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_source_digest", sa.String(length=71), nullable=False),
        sa.Column("provider_name", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("provider_contract_version", sa.String(length=20), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("input_digest", sa.String(length=71), nullable=False),
        sa.Column("output_digest", sa.String(length=71), nullable=False),
        sa.Column("summary_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "review_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "patient_id",
            "summary_version",
            name="uq_ai_case_summary_patient_version",
        ),
    )
    op.create_index(
        "ix_ai_case_summaries_clinic_id",
        "ai_case_summaries",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_case_summaries_patient_id",
        "ai_case_summaries",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "idx_ai_case_summary_latest",
        "ai_case_summaries",
        ["clinic_id", "patient_id", "summary_version"],
        unique=False,
    )
    op.create_index(
        "idx_ai_case_summary_snapshot",
        "ai_case_summaries",
        ["clinic_id", "patient_id", "case_snapshot_version", "input_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ai_case_summary_snapshot", table_name="ai_case_summaries")
    op.drop_index("idx_ai_case_summary_latest", table_name="ai_case_summaries")
    op.drop_index("ix_ai_case_summaries_patient_id", table_name="ai_case_summaries")
    op.drop_index("ix_ai_case_summaries_clinic_id", table_name="ai_case_summaries")
    op.drop_table("ai_case_summaries")
