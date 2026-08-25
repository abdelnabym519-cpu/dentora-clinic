"""dental_3d deterministic patient-space implant planning.

Revision ID: d3d_0006
Revises: d3d_0005
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3d_0006"
down_revision: str | None = "d3d_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dental_prosthetic_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform_center", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("axis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("frame_of_reference_uid", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference_space", sa.String(length=20), nullable=False),
        sa.Column("source_frame_of_reference_uid", sa.String(length=64), nullable=True),
        sa.Column("source_method", sa.String(length=100), nullable=False),
        sa.Column("source_identifier", sa.String(length=255), nullable=False),
        sa.Column("source_digest", sa.String(length=71), nullable=True),
        sa.Column(
            "source_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending_review",
        ),
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
            "review_status IN ('pending_review', 'accepted', 'rejected')",
            name="ck_dental_prosthetic_target_review_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('dentist_defined', 'registered_ios', "
            "'prosthetic_scan', 'prosthetic_design')",
            name="ck_dental_prosthetic_target_source_type",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["alignment_id"], ["dental_alignment_results.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dental_prosthetic_targets_clinic_id",
        "dental_prosthetic_targets",
        ["clinic_id"],
    )
    op.create_index(
        "ix_dental_prosthetic_targets_patient_id",
        "dental_prosthetic_targets",
        ["patient_id"],
    )
    op.create_index(
        "ix_dental_prosthetic_targets_alignment_id",
        "dental_prosthetic_targets",
        ["alignment_id"],
    )
    op.create_index(
        "idx_dental_prosthetic_target_latest",
        "dental_prosthetic_targets",
        ["clinic_id", "patient_id", "created_at"],
    )

    op.create_table(
        "dental_implant_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column(
            "current_revision_number", sa.Integer(), nullable=False, server_default="1"
        ),
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
            "status IN ('draft', 'proposed', 'accepted', 'rejected')",
            name="ck_dental_implant_plan_status",
        ),
        sa.CheckConstraint(
            "current_revision_number >= 1",
            name="ck_dental_implant_plan_revision_positive",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dental_implant_plans_clinic_id",
        "dental_implant_plans",
        ["clinic_id"],
    )
    op.create_index(
        "ix_dental_implant_plans_patient_id",
        "dental_implant_plans",
        ["patient_id"],
    )
    op.create_index(
        "idx_dental_implant_plan_patient",
        "dental_implant_plans",
        ["clinic_id", "patient_id", "created_at"],
    )

    op.create_table(
        "dental_implant_plan_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("candidate", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("planning_case", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_dental_implant_plan_revision_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["dental_implant_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "revision_number",
            name="uq_dental_implant_plan_revision_number",
        ),
    )
    op.create_index(
        "ix_dental_implant_plan_revisions_plan_id",
        "dental_implant_plan_revisions",
        ["plan_id"],
    )
    op.create_index(
        "ix_dental_implant_plan_revisions_clinic_id",
        "dental_implant_plan_revisions",
        ["clinic_id"],
    )
    op.create_index(
        "ix_dental_implant_plan_revisions_patient_id",
        "dental_implant_plan_revisions",
        ["patient_id"],
    )
    op.create_index(
        "idx_dental_implant_revision_patient",
        "dental_implant_plan_revisions",
        ["clinic_id", "patient_id", "plan_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_dental_implant_revision_patient",
        table_name="dental_implant_plan_revisions",
    )
    op.drop_index(
        "ix_dental_implant_plan_revisions_patient_id",
        table_name="dental_implant_plan_revisions",
    )
    op.drop_index(
        "ix_dental_implant_plan_revisions_clinic_id",
        table_name="dental_implant_plan_revisions",
    )
    op.drop_index(
        "ix_dental_implant_plan_revisions_plan_id",
        table_name="dental_implant_plan_revisions",
    )
    op.drop_table("dental_implant_plan_revisions")

    op.drop_index("idx_dental_implant_plan_patient", table_name="dental_implant_plans")
    op.drop_index("ix_dental_implant_plans_patient_id", table_name="dental_implant_plans")
    op.drop_index("ix_dental_implant_plans_clinic_id", table_name="dental_implant_plans")
    op.drop_table("dental_implant_plans")

    op.drop_index(
        "idx_dental_prosthetic_target_latest",
        table_name="dental_prosthetic_targets",
    )
    op.drop_index(
        "ix_dental_prosthetic_targets_alignment_id",
        table_name="dental_prosthetic_targets",
    )
    op.drop_index(
        "ix_dental_prosthetic_targets_patient_id",
        table_name="dental_prosthetic_targets",
    )
    op.drop_index(
        "ix_dental_prosthetic_targets_clinic_id",
        table_name="dental_prosthetic_targets",
    )
    op.drop_table("dental_prosthetic_targets")
