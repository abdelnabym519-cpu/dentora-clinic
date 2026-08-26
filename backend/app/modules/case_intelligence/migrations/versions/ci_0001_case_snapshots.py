"""case_intelligence append-only unified case snapshots.

Revision ID: ci_0001
Revises: 0001
Depends on: d3d_0006
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "ci_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "d3d_0006"


def upgrade() -> None:
    op.create_table(
        "case_intelligence_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("source_digest", sa.String(length=71), nullable=False),
        sa.Column("snapshot_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "source_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "patient_id",
            "snapshot_version",
            name="uq_case_intelligence_patient_snapshot_version",
        ),
    )
    op.create_index(
        "ix_case_intelligence_snapshots_clinic_id",
        "case_intelligence_snapshots",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        "ix_case_intelligence_snapshots_patient_id",
        "case_intelligence_snapshots",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "idx_case_intelligence_latest",
        "case_intelligence_snapshots",
        ["clinic_id", "patient_id", "snapshot_version"],
        unique=False,
    )
    op.create_index(
        "idx_case_intelligence_source_digest",
        "case_intelligence_snapshots",
        ["clinic_id", "patient_id", "source_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_case_intelligence_source_digest", table_name="case_intelligence_snapshots")
    op.drop_index("idx_case_intelligence_latest", table_name="case_intelligence_snapshots")
    op.drop_index(
        "ix_case_intelligence_snapshots_patient_id",
        table_name="case_intelligence_snapshots",
    )
    op.drop_index(
        "ix_case_intelligence_snapshots_clinic_id",
        table_name="case_intelligence_snapshots",
    )
    op.drop_table("case_intelligence_snapshots")
