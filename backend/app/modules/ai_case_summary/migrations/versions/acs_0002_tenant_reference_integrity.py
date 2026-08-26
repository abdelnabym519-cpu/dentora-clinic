"""ai_case_summary: enforce tenant-safe patient references.

Revision ID: acs_0002
Revises: acs_0001
Create Date: 2026-08-26

AI summaries carry both ``patient_id`` and ``clinic_id``.  Refuse existing
cross-clinic rows and then bind the pair to ``patients(id, clinic_id)`` so the
database rejects future tenant mismatches.  The migration depends on
``ci_0002`` because AI Case Summary already depends on Case Intelligence.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "acs_0002"
down_revision: str | None = "acs_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "ci_0002"


def upgrade() -> None:
    bind = op.get_bind()
    mismatch = bind.execute(
        sa.text(
            """
            SELECT s.id, s.patient_id, s.clinic_id, p.clinic_id AS patient_clinic_id
            FROM ai_case_summaries AS s
            JOIN patients AS p ON p.id = s.patient_id
            WHERE s.clinic_id <> p.clinic_id
            LIMIT 1
            """
        )
    ).first()
    if mismatch is not None:
        raise RuntimeError(
            "Cannot enforce AI Case Summary tenant integrity: summary "
            f"{mismatch.id} stores clinic {mismatch.clinic_id} while patient "
            f"{mismatch.patient_id} belongs to {mismatch.patient_clinic_id}"
        )

    op.create_foreign_key(
        "fk_ai_case_summary_patient_clinic",
        "ai_case_summaries",
        "patients",
        ["patient_id", "clinic_id"],
        ["id", "clinic_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_case_summary_patient_clinic",
        "ai_case_summaries",
        type_="foreignkey",
    )
