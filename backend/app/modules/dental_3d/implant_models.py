"""Persistence models for deterministic patient-space implant planning."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


class DentalProstheticTarget(Base, TimestampMixin):
    """Explicit prosthetic target tied to one accepted patient alignment."""

    __tablename__ = "dental_prosthetic_targets"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    alignment_id: Mapped[UUID] = mapped_column(ForeignKey("dental_alignment_results.id"), index=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    platform_center: Mapped[dict] = mapped_column(JSONB)
    axis: Mapped[dict] = mapped_column(JSONB)
    frame_of_reference_uid: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(32))
    source_reference_space: Mapped[str] = mapped_column(String(20))
    source_frame_of_reference_uid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_method: Mapped[str] = mapped_column(String(100))
    source_identifier: Mapped[str] = mapped_column(String(255))
    source_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    source_document_ids: Mapped[list] = mapped_column(JSONB, default=list)

    review_status: Mapped[str] = mapped_column(String(20), default="pending_review")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    clinic: Mapped[Clinic] = relationship()
    patient: Mapped[Patient] = relationship()
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending_review', 'accepted', 'rejected')",
            name="ck_dental_prosthetic_target_review_status",
        ),
        CheckConstraint(
            "source_type IN ('dentist_defined', 'registered_ios', "
            "'prosthetic_scan', 'prosthetic_design')",
            name="ck_dental_prosthetic_target_source_type",
        ),
        Index(
            "idx_dental_prosthetic_target_latest",
            "clinic_id",
            "patient_id",
            "created_at",
        ),
    )


class DentalImplantPlan(Base, TimestampMixin):
    """Mutable plan identity; clinical geometry lives in immutable revisions."""

    __tablename__ = "dental_implant_plans"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    clinic: Mapped[Clinic] = relationship()
    patient: Mapped[Patient] = relationship()
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'proposed', 'accepted', 'rejected')",
            name="ck_dental_implant_plan_status",
        ),
        CheckConstraint(
            "current_revision_number >= 1",
            name="ck_dental_implant_plan_revision_positive",
        ),
        Index(
            "idx_dental_implant_plan_patient",
            "clinic_id",
            "patient_id",
            "created_at",
        ),
    )


class DentalImplantPlanRevision(Base):
    """Immutable snapshot of candidate, measurements and source case."""

    __tablename__ = "dental_implant_plan_revisions"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("dental_implant_plans.id", ondelete="CASCADE"), index=True
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    candidate: Mapped[dict] = mapped_column(JSONB)
    assessment: Mapped[dict] = mapped_column(JSONB)
    planning_case: Mapped[dict] = mapped_column(JSONB)
    policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "revision_number",
            name="uq_dental_implant_plan_revision_number",
        ),
        CheckConstraint(
            "revision_number >= 1",
            name="ck_dental_implant_plan_revision_number_positive",
        ),
        Index(
            "idx_dental_implant_revision_patient",
            "clinic_id",
            "patient_id",
            "plan_id",
        ),
    )


__all__ = [
    "DentalImplantPlan",
    "DentalImplantPlanRevision",
    "DentalProstheticTarget",
]
