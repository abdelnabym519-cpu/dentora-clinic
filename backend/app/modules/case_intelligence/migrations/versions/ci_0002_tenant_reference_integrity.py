"""case_intelligence: enforce tenant-safe patient references.

Revision ID: ci_0002
Revises: ci_0001
Create Date: 2026-08-26

Case snapshots carry both ``patient_id`` and ``clinic_id``.  Refuse existing
cross-clinic rows and then bind the pair to ``patients(id, clinic_id)`` so the
database rejects future tenant mismatches without rewriting clinical data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ci_0002"
down_revision: str | None = "ci_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "pat_0004"


def upgrade() -> None:
    bind = op.get_bind()
    mismatch = bind.execute(
        sa.text(
            """
            SELECT s.id, s.patient_id, s.clinic_id, p.clinic_id AS patient_clinic_id
            FROM case_intelligence_snapshots AS s
            JOIN patients AS p ON p.id = s.patient_id
            WHERE s.clinic_id <> p.clinic_id
            LIMIT 1
            """
        )
    ).first()
    if mismatch is not None:
        raise RuntimeError(
            "Cannot enforce Case Intelligence tenant integrity: snapshot "
            f"{mismatch.id} stores clinic {mismatch.clinic_id} while patient "
            f"{mismatch.patient_id} belongs to {mismatch.patient_clinic_id}"
        )

    op.create_foreign_key(
        "fk_case_intelligence_patient_clinic",
        "case_intelligence_snapshots",
        "patients",
        ["patient_id", "clinic_id"],
        ["id", "clinic_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_case_intelligence_patient_clinic",
        "case_intelligence_snapshots",
        type_="foreignkey",
    )
