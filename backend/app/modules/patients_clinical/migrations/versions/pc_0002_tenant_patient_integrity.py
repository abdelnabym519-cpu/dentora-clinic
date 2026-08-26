"""patients_clinical: enforce patient/clinic tenant integrity.

Revision ID: pc_0002
Revises: pc_0001
Create Date: 2026-08-26

Every clinical row already stores both patient_id and clinic_id.  This revision
makes their agreement a PostgreSQL invariant rather than a service-layer
assumption.  Legacy mismatches fail the migration closed and are never
rewritten automatically.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "pc_0002"
down_revision: str | None = "pc_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "pat_0004"

_TABLES = (
    ("patients_clinical_medical_context", "fk_pc_medical_context_patient_clinic"),
    ("patients_clinical_allergy", "fk_pc_allergy_patient_clinic"),
    ("patients_clinical_medication", "fk_pc_medication_patient_clinic"),
    ("patients_clinical_systemic_disease", "fk_pc_disease_patient_clinic"),
    ("patients_clinical_surgical_history", "fk_pc_surgery_patient_clinic"),
    ("patients_clinical_emergency_contact", "fk_pc_emergency_patient_clinic"),
    ("patients_clinical_legal_guardian", "fk_pc_guardian_patient_clinic"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name, constraint_name in _TABLES:
        mismatch = bind.execute(
            sa.text(
                f"""
                SELECT child.patient_id, child.clinic_id, patient.clinic_id AS patient_clinic_id
                FROM {table_name} AS child
                JOIN patients AS patient ON patient.id = child.patient_id
                WHERE child.clinic_id <> patient.clinic_id
                LIMIT 1
                """
            )
        ).first()
        if mismatch is not None:
            raise RuntimeError(
                f"Cannot enforce tenant integrity on {table_name}: patient "
                f"{mismatch.patient_id} belongs to clinic {mismatch.patient_clinic_id}, "
                f"row stores clinic {mismatch.clinic_id}"
            )

        op.create_foreign_key(
            constraint_name,
            table_name,
            "patients",
            ["patient_id", "clinic_id"],
            ["id", "clinic_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table_name, constraint_name in reversed(_TABLES):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
