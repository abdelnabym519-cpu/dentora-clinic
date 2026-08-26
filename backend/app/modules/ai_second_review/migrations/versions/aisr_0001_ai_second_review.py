"""AI Second Review append-only artifacts.

Revision ID: aisr_0001
Revises: tsim_0001
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "aisr_0001"
down_revision: str | None = "tsim_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_second_review_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("case_snapshot_contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_source_digest", sa.String(length=71), nullable=False),
        sa.Column("risk_engine_version", sa.String(length=40), nullable=False),
        sa.Column("risk_policy_version", sa.String(length=80), nullable=False),
        sa.Column("risk_input_digest", sa.String(length=71), nullable=False),
        sa.Column("risk_result_digest", sa.String(length=71), nullable=False),
        sa.Column("planning_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planning_version", sa.Integer(), nullable=False),
        sa.Column("planning_output_digest", sa.String(length=71), nullable=False),
        sa.Column("planning_reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planning_reviewed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("option_id", sa.String(length=40), nullable=False),
        sa.Column("simulation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("simulation_version", sa.Integer(), nullable=False),
        sa.Column("simulation_engine_version", sa.String(length=40), nullable=False),
        sa.Column("simulation_input_digest", sa.String(length=71), nullable=False),
        sa.Column("simulation_output_digest", sa.String(length=71), nullable=False),
        sa.Column("provider_name", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("provider_contract_version", sa.String(length=30), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("input_contract_version", sa.String(length=20), nullable=False),
        sa.Column("input_digest", sa.String(length=71), nullable=False),
        sa.Column("output_digest", sa.String(length=71), nullable=False),
        sa.Column("review_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["planning_id"], ["ai_treatment_planning_results.id"]),
        sa.ForeignKeyConstraint(["simulation_id"], ["treatment_simulation_results.id"]),
        sa.ForeignKeyConstraint(["planning_reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "patient_id",
            "review_version",
            name="uq_ai_second_review_patient_version",
        ),
    )
    op.create_index(
        "ix_ai_second_review_results_clinic_id",
        "ai_second_review_results",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_second_review_results_patient_id",
        "ai_second_review_results",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_second_review_results_planning_id",
        "ai_second_review_results",
        ["planning_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_second_review_results_simulation_id",
        "ai_second_review_results",
        ["simulation_id"],
        unique=False,
    )
    op.create_index(
        "idx_ai_second_review_latest",
        "ai_second_review_results",
        ["clinic_id", "patient_id", "review_version"],
        unique=False,
    )
    op.create_index(
        "idx_ai_second_review_simulation",
        "ai_second_review_results",
        ["clinic_id", "patient_id", "simulation_id"],
        unique=False,
    )
    op.create_index(
        "idx_ai_second_review_input",
        "ai_second_review_results",
        ["clinic_id", "patient_id", "input_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ai_second_review_input", table_name="ai_second_review_results")
    op.drop_index("idx_ai_second_review_simulation", table_name="ai_second_review_results")
    op.drop_index("idx_ai_second_review_latest", table_name="ai_second_review_results")
    op.drop_index(
        "ix_ai_second_review_results_simulation_id",
        table_name="ai_second_review_results",
    )
    op.drop_index(
        "ix_ai_second_review_results_planning_id",
        table_name="ai_second_review_results",
    )
    op.drop_index(
        "ix_ai_second_review_results_patient_id",
        table_name="ai_second_review_results",
    )
    op.drop_index(
        "ix_ai_second_review_results_clinic_id",
        table_name="ai_second_review_results",
    )
    op.drop_table("ai_second_review_results")
