"""Risk Engine append-only results and review state.

Revision ID: risk_0001
Revises: acs_0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "risk_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("risk_engine",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("case_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("case_snapshot_contract_version", sa.String(length=20), nullable=False),
        sa.Column("source_digest", sa.String(length=71), nullable=False),
        sa.Column("input_digest", sa.String(length=71), nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("availability_state", sa.String(length=30), nullable=False),
        sa.Column("result_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "result_version",
            name="uq_risk_result_patient_version",
        ),
    )
    op.create_index("ix_risk_results_clinic_id", "risk_results", ["clinic_id"], unique=False)
    op.create_index("ix_risk_results_patient_id", "risk_results", ["patient_id"], unique=False)
    op.create_index(
        "idx_risk_result_latest",
        "risk_results",
        ["clinic_id", "patient_id", "result_version"],
        unique=False,
    )
    op.create_index(
        "idx_risk_result_snapshot",
        "risk_results",
        ["clinic_id", "patient_id", "case_snapshot_version", "input_digest"],
        unique=False,
    )
    op.create_index(
        "idx_risk_result_digest",
        "risk_results",
        ["clinic_id", "patient_id", "result_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_risk_result_digest", table_name="risk_results")
    op.drop_index("idx_risk_result_snapshot", table_name="risk_results")
    op.drop_index("idx_risk_result_latest", table_name="risk_results")
    op.drop_index("ix_risk_results_patient_id", table_name="risk_results")
    op.drop_index("ix_risk_results_clinic_id", table_name="risk_results")
    op.drop_table("risk_results")
