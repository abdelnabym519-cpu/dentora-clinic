"""dental_3d Phase 5.2 — explicit CBCT nerve-inference outcomes.

Revision ID: d3d_0004
Revises: d3d_0003
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3d_0004"
down_revision: str | None = "d3d_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dental_nerve_analyses",
        sa.Column("detection_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "dental_nerve_analyses",
        sa.Column("input_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "dental_nerve_analyses",
        sa.Column("failure_code", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "dental_nerve_analyses",
        sa.Column("failure_message", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "dental_nerve_analyses",
        sa.Column(
            "analysis_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE dental_nerve_analyses SET detection_status = 'uncertain', "
        "input_kind = 'scene', analysis_metadata = '{}'::jsonb"
    )
    op.alter_column("dental_nerve_analyses", "detection_status", nullable=False)
    op.alter_column("dental_nerve_analyses", "input_kind", nullable=False)
    op.alter_column("dental_nerve_analyses", "analysis_metadata", nullable=False)
    op.drop_constraint(
        "ck_dental_nerve_review_status",
        "dental_nerve_analyses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dental_nerve_review_status",
        "dental_nerve_analyses",
        "review_status IN ('pending', 'accepted', 'rejected', 'not_applicable')",
    )
    op.create_check_constraint(
        "ck_dental_nerve_detection_status",
        "dental_nerve_analyses",
        "detection_status IN ('detected', 'no_detection', 'uncertain', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_dental_nerve_detection_status",
        "dental_nerve_analyses",
        type_="check",
    )
    op.drop_constraint(
        "ck_dental_nerve_review_status",
        "dental_nerve_analyses",
        type_="check",
    )
    # Phase 4 has no non-reviewable failure state. Preserve the safest
    # terminal interpretation rather than making a failed operation reviewable.
    op.execute(
        "UPDATE dental_nerve_analyses SET review_status = 'rejected' "
        "WHERE review_status = 'not_applicable'"
    )
    op.create_check_constraint(
        "ck_dental_nerve_review_status",
        "dental_nerve_analyses",
        "review_status IN ('pending', 'accepted', 'rejected')",
    )
    op.drop_column("dental_nerve_analyses", "analysis_metadata")
    op.drop_column("dental_nerve_analyses", "failure_message")
    op.drop_column("dental_nerve_analyses", "failure_code")
    op.drop_column("dental_nerve_analyses", "input_kind")
    op.drop_column("dental_nerve_analyses", "detection_status")
