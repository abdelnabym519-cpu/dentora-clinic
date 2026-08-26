"""media: enforce tenant-safe document references.

Revision ID: med_0003
Revises: med_0002
Create Date: 2026-08-26

Documents must belong to the same clinic as their patient, and attachments must
belong to the same clinic as their document.  Preflight existing rows and fail
closed instead of rewriting clinical/media ownership.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "med_0003"
down_revision: str | None = "med_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = "pat_0004"


def upgrade() -> None:
    bind = op.get_bind()

    mismatch = bind.execute(
        sa.text(
            """
            SELECT d.id, d.patient_id, d.clinic_id, p.clinic_id AS patient_clinic_id
            FROM documents AS d
            JOIN patients AS p ON p.id = d.patient_id
            WHERE d.clinic_id <> p.clinic_id
            LIMIT 1
            """
        )
    ).first()
    if mismatch is not None:
        raise RuntimeError(
            "Cannot enforce document tenant integrity: document "
            f"{mismatch.id} stores clinic {mismatch.clinic_id} while patient "
            f"{mismatch.patient_id} belongs to {mismatch.patient_clinic_id}"
        )

    attachment_mismatch = bind.execute(
        sa.text(
            """
            SELECT a.id, a.clinic_id, d.clinic_id AS document_clinic_id
            FROM media_attachments AS a
            JOIN documents AS d ON d.id = a.document_id
            WHERE a.clinic_id <> d.clinic_id
            LIMIT 1
            """
        )
    ).first()
    if attachment_mismatch is not None:
        raise RuntimeError(
            "Cannot enforce media attachment tenant integrity: attachment "
            f"{attachment_mismatch.id} stores clinic {attachment_mismatch.clinic_id} "
            f"while its document belongs to {attachment_mismatch.document_clinic_id}"
        )

    op.create_unique_constraint(
        "uq_documents_id_clinic",
        "documents",
        ["id", "clinic_id"],
    )
    op.create_foreign_key(
        "fk_documents_patient_clinic",
        "documents",
        "patients",
        ["patient_id", "clinic_id"],
        ["id", "clinic_id"],
    )
    op.create_foreign_key(
        "fk_media_attachments_document_clinic",
        "media_attachments",
        "documents",
        ["document_id", "clinic_id"],
        ["id", "clinic_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_media_attachments_document_clinic",
        "media_attachments",
        type_="foreignkey",
    )
    op.drop_constraint("fk_documents_patient_clinic", "documents", type_="foreignkey")
    op.drop_constraint("uq_documents_id_clinic", "documents", type_="unique")
