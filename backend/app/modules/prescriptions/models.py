"""SQLAlchemy persistence models for Electronic Prescription."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class PrescriptionRecord(Base, TimestampMixin):
    __tablename__ = "prescriptions"
    __table_args__ = (
        UniqueConstraint("identifier", name="uq_prescriptions_identifier"),
        Index("ix_prescriptions_scope_patient", "tenant_id", "clinic_id", "patient_id"),
        Index("ix_prescriptions_scope_status", "tenant_id", "clinic_id", "status"),
        Index("ix_prescriptions_scope_doctor", "tenant_id", "clinic_id", "doctor_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    clinic_id: Mapped[UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    doctor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    identifier: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    void_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list[PrescriptionItemRecord]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PrescriptionItemRecord.position",
    )


class PrescriptionItemRecord(Base):
    __tablename__ = "prescription_items"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    prescription_id: Mapped[UUID] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    medication_name: Mapped[str] = mapped_column(String(200), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(100))
    dose: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[str] = mapped_column(String(100), nullable=False)
    duration: Mapped[str] = mapped_column(String(100), nullable=False)
    route: Mapped[str] = mapped_column(String(100), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_unit: Mapped[str | None] = mapped_column(String(50))

    prescription: Mapped[PrescriptionRecord] = relationship(back_populates="items")


class PrescriptionAuditRecord(Base):
    __tablename__ = "prescription_audit_events"
    __table_args__ = (
        Index("ix_prescription_audit_scope", "tenant_id", "clinic_id", "prescription_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    clinic_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    prescription_id: Mapped[UUID] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
