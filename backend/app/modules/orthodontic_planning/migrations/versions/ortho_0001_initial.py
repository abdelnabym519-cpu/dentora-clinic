"""orthodontic_planning module — initial schema.

Revision ID: ortho_0001
Revises: 0006
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "ortho_0001"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = ("orthodontic_planning",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ortho_assessments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("skeletal_pattern", sa.String(length=12), nullable=True),
        sa.Column("growth_stage", sa.String(length=12), nullable=True),
        sa.Column("overjet_mm", sa.Float(), nullable=True),
        sa.Column("overbite_mm", sa.Float(), nullable=True),
        sa.Column("crowding_upper_mm", sa.Float(), nullable=True),
        sa.Column("crowding_lower_mm", sa.Float(), nullable=True),
        sa.Column("molar_relation_left", sa.String(length=12), nullable=True),
        sa.Column("molar_relation_right", sa.String(length=12), nullable=True),
        sa.Column("canine_relation_left", sa.String(length=12), nullable=True),
        sa.Column("canine_relation_right", sa.String(length=12), nullable=True),
        sa.Column("posterior_crossbite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("objectives", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dentition_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_sufficiency", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "skeletal_pattern IN ('class_i', 'class_ii', 'class_iii') OR skeletal_pattern IS NULL",
            name="ck_ortho_assessment_skeletal",
        ),
        sa.CheckConstraint(
            "growth_stage IN ('adolescent', 'adult') OR growth_stage IS NULL",
            name="ck_ortho_assessment_growth",
        ),
        sa.CheckConstraint(
            "molar_relation_left IN ('class_i', 'class_ii', 'class_iii') OR "
            "molar_relation_left IS NULL",
            name="ck_ortho_assessment_molar_l",
        ),
        sa.CheckConstraint(
            "molar_relation_right IN ('class_i', 'class_ii', 'class_iii') OR "
            "molar_relation_right IS NULL",
            name="ck_ortho_assessment_molar_r",
        ),
        sa.CheckConstraint(
            "canine_relation_left IN ('class_i', 'class_ii', 'class_iii') OR "
            "canine_relation_left IS NULL",
            name="ck_ortho_assessment_canine_l",
        ),
        sa.CheckConstraint(
            "canine_relation_right IN ('class_i', 'class_ii', 'class_iii') OR "
            "canine_relation_right IS NULL",
            name="ck_ortho_assessment_canine_r",
        ),
        sa.CheckConstraint(
            "(overjet_mm IS NULL) OR (overjet_mm BETWEEN -10 AND 15)",
            name="ck_ortho_assessment_overjet",
        ),
        sa.CheckConstraint(
            "(overbite_mm IS NULL) OR (overbite_mm BETWEEN -10 AND 15)",
            name="ck_ortho_assessment_overbite",
        ),
        sa.CheckConstraint(
            "(crowding_upper_mm IS NULL) OR (crowding_upper_mm BETWEEN 0 AND 20)",
            name="ck_ortho_assessment_crowding_upper",
        ),
        sa.CheckConstraint(
            "(crowding_lower_mm IS NULL) OR (crowding_lower_mm BETWEEN 0 AND 20)",
            name="ck_ortho_assessment_crowding_lower",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ortho_assessments_clinic_id", "ortho_assessments", ["clinic_id"])
    op.create_index("ix_ortho_assessments_patient_id", "ortho_assessments", ["patient_id"])
    op.create_index(
        "ix_ortho_assessment_patient_created",
        "ortho_assessments",
        ["patient_id", "created_at"],
    )

    op.create_table(
        "ortho_plan_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_version", sa.String(length=40), nullable=False),
        sa.Column(
            "constraints_version",
            sa.String(length=40),
            nullable=False,
            server_default="ortho-constraints-2026.09",
        ),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="draft"),
        sa.Column("stage_count", sa.Integer(), nullable=False),
        sa.Column("planned_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("stages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("constraint_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("uncertainty", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_ortho_proposal_status",
        ),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_ortho_proposal_score"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ortho_proposal_confidence"
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["assessment_id"], ["ortho_assessments.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ortho_plan_proposals_clinic_id", "ortho_plan_proposals", ["clinic_id"])
    op.create_index("ix_ortho_plan_proposals_patient_id", "ortho_plan_proposals", ["patient_id"])
    op.create_index(
        "ix_ortho_plan_proposals_assessment_id", "ortho_plan_proposals", ["assessment_id"]
    )
    op.create_index(
        "ix_ortho_proposal_patient_status",
        "ortho_plan_proposals",
        ["patient_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ortho_proposal_patient_status", table_name="ortho_plan_proposals")
    op.drop_index("ix_ortho_plan_proposals_assessment_id", table_name="ortho_plan_proposals")
    op.drop_index("ix_ortho_plan_proposals_patient_id", table_name="ortho_plan_proposals")
    op.drop_index("ix_ortho_plan_proposals_clinic_id", table_name="ortho_plan_proposals")
    op.drop_table("ortho_plan_proposals")
    op.drop_index("ix_ortho_assessment_patient_created", table_name="ortho_assessments")
    op.drop_index("ix_ortho_assessments_patient_id", table_name="ortho_assessments")
    op.drop_index("ix_ortho_assessments_clinic_id", table_name="ortho_assessments")
    op.drop_table("ortho_assessments")
