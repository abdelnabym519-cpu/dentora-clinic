"""electronic prescription initial schema.

Revision ID: rx_0001
Revises: None
Depends on: core 0007 + patients pat_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "rx_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("prescriptions",)
depends_on: str | Sequence[str] | None = ("0007", "pat_0003")


def upgrade() -> None:
    op.create_table(
        "prescriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identifier", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("void_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["doctor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("identifier", name="uq_prescriptions_identifier"),
        sa.CheckConstraint(
            "status IN ('draft','issued','cancelled','voided')",
            name="ck_prescriptions_status",
        ),
    )
    op.create_index(
        "ix_prescriptions_scope_patient",
        "prescriptions",
        ["tenant_id", "clinic_id", "patient_id"],
    )
    op.create_index(
        "ix_prescriptions_scope_status",
        "prescriptions",
        ["tenant_id", "clinic_id", "status"],
    )
    op.create_index(
        "ix_prescriptions_scope_doctor",
        "prescriptions",
        ["tenant_id", "clinic_id", "doctor_id"],
    )

    op.create_table(
        "prescription_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("medication_name", sa.String(200), nullable=False),
        sa.Column("strength", sa.String(100)),
        sa.Column("dose", sa.String(100), nullable=False),
        sa.Column("frequency", sa.String(100), nullable=False),
        sa.Column("duration", sa.String(100), nullable=False),
        sa.Column("route", sa.String(100), nullable=False),
        sa.Column("instructions", sa.Text()),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("quantity_unit", sa.String(50)),
        sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("quantity > 0", name="ck_prescription_items_quantity"),
    )
    op.create_index(
        "ix_prescription_items_prescription_id", "prescription_items", ["prescription_id"]
    )

    op.create_table(
        "prescription_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prescription_id"], ["prescriptions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_prescription_audit_scope",
        "prescription_audit_events",
        ["tenant_id", "clinic_id", "prescription_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_prescription_audit_scope", table_name="prescription_audit_events")
    op.drop_table("prescription_audit_events")
    op.drop_index("ix_prescription_items_prescription_id", table_name="prescription_items")
    op.drop_table("prescription_items")
    op.drop_index("ix_prescriptions_scope_doctor", table_name="prescriptions")
    op.drop_index("ix_prescriptions_scope_status", table_name="prescriptions")
    op.drop_index("ix_prescriptions_scope_patient", table_name="prescriptions")
    op.drop_table("prescriptions")
