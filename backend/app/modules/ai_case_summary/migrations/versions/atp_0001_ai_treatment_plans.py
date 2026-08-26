"""AI Treatment Planning append-only advisory drafts.

Revision ID: atp_0001
Revises: risk_0001
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "atp_0001"
down_revision: str | None = "risk_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_treatment_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("case_snapshot_contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_source_digest", sa.String(length=71), nullable=False),
        sa.Column("summary_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_version", sa.Integer(), nullable=False),
        sa.Column("summary_output_digest", sa.String(length=71), nullable=False),
        sa.Column("risk_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("risk_result_version", sa.Integer(), nullable=False),
        sa.Column("risk_result_digest", sa.String(length=71), nullable=False),
        sa.Column("provider_name", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("provider_contract_version", sa.String(length=20), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("input_digest", sa.String(length=71), nullable=False),
        sa.Column("output_digest", sa.String(length=71), nullable=False),
        sa.Column("plan_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.ForeignKeyConstraint(["summary_id"], ["ai_case_summaries.id"]),
        sa.ForeignKeyConstraint(["risk_result_id"], ["risk_results.id"]),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "patient_id",
            "plan_version",
            name="uq_ai_treatment_plan_patient_version",
        ),
    )
    op.create_index(
        "ix_ai_treatment_plans_clinic_id",
        "ai_treatment_plans",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_treatment_plans_patient_id",
        "ai_treatment_plans",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "idx_ai_treatment_plan_latest",
        "ai_treatment_plans",
        ["clinic_id", "patient_id", "plan_version"],
        unique=False,
    )
    op.create_index(
        "idx_ai_treatment_plan_snapshot",
        "ai_treatment_plans",
        ["clinic_id", "patient_id", "case_snapshot_version", "input_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ai_treatment_plan_snapshot", table_name="ai_treatment_plans")
    op.drop_index("idx_ai_treatment_plan_latest", table_name="ai_treatment_plans")
    op.drop_index("ix_ai_treatment_plans_patient_id", table_name="ai_treatment_plans")
    op.drop_index("ix_ai_treatment_plans_clinic_id", table_name="ai_treatment_plans")
    op.drop_table("ai_treatment_plans")
