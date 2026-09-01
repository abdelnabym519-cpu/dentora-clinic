"""dental_3d module — initial schema.

Revision ID: d3d_0001
Revises: 0001
Create Date: 2026-08-23

Isolated Alembic branch (``dental_3d``) per ADR 0002 — uninstall of
the module downgrades only this chain, leaving every other module's
tables untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3d_0001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = ("dental_3d",)
# d3d tables FK patients, created by ``pat_0001`` on the main chain. Without
# this edge alembic may run d3d_0001 (branched off 0001) before pat_0001 on
# a clean upgrade, so the FK target doesn't exist yet. depends_on forces the
# correct order (same pattern as cop_0001).
depends_on: str | Sequence[str] | None = "pat_0001"


def upgrade() -> None:
    op.create_table(
        "dental_scenes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("generator", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("teeth", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("segmentation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_dental_scene_status"),
        sa.CheckConstraint(
            "generator IN ('synthetic', 'segmentation', 'cbct', "
            "'intraoral_scan', 'face_scan', 'digital_twin')",
            name="ck_dental_scene_generator",
        ),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_id", name="uq_dental_scene_patient"),
    )
    op.create_index(
        op.f("ix_dental_scenes_clinic_id"),
        "dental_scenes",
        ["clinic_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dental_scenes_patient_id"),
        "dental_scenes",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "idx_dental_scenes_clinic_patient",
        "dental_scenes",
        ["clinic_id", "patient_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_dental_scenes_clinic_patient", table_name="dental_scenes")
    op.drop_index(op.f("ix_dental_scenes_patient_id"), table_name="dental_scenes")
    op.drop_index(op.f("ix_dental_scenes_clinic_id"), table_name="dental_scenes")
    op.drop_table("dental_scenes")
