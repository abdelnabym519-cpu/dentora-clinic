"""patients: expose a tenant-safe composite reference key.

Revision ID: pat_0004
Revises: pat_0003
Create Date: 2026-08-26

``patients.id`` remains the public primary key.  The composite uniqueness is
intentionally redundant so tenant-owned child tables can reference
``(patient_id, clinic_id)`` and let PostgreSQL reject cross-clinic linkage.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "pat_0004"
down_revision: str | None = "pat_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_patients_id_clinic",
        "patients",
        ["id", "clinic_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_patients_id_clinic",
        "patients",
        type_="unique",
    )
