"""pathology_detection module — initial schema.

Revision ID: pathology_0001
Revises: 0006
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "pathology_0001"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = ("pathology_detection",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pathology_analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("engine", sa.String(length=40), nullable=True),
        sa.Column("model_version", sa.String(length=80), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("findings_count", sa.Integer(), nullable=False),
        sa.Column("inference_ms", sa.Integer(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_pathology_analysis_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pathology_analyses_clinic_id",
        "pathology_analyses",
        ["clinic_id"],
    )
    op.create_index(
        "ix_pathology_analyses_patient_id",
        "pathology_analyses",
        ["patient_id"],
    )
    op.create_index(
        "ix_pathology_analyses_document_id",
        "pathology_analyses",
        ["document_id"],
    )
    op.create_index(
        "ix_pathology_analysis_patient_status",
        "pathology_analyses",
        ["patient_id", "status"],
    )

    op.create_table(
        "pathology_findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("diagnosis", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tooth_number", sa.Integer(), nullable=True),
        sa.Column("quadrant", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "diagnosis IN ('caries', 'deep_caries', 'periapical_lesion', 'impacted_tooth')",
            name="ck_pathology_finding_diagnosis",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["pathology_analyses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pathology_findings_analysis_id",
        "pathology_findings",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_table("pathology_findings")
    op.drop_table("pathology_analyses")
