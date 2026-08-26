"""AI Treatment Planning persistence; append-only advisory drafts only."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


class AITreatmentPlanRecord(Base):
    __tablename__ = "ai_treatment_plans"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    case_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    case_snapshot_contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    case_source_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    summary_id: Mapped[UUID] = mapped_column(ForeignKey("ai_case_summaries.id"), nullable=False)
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_output_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    risk_result_id: Mapped[UUID] = mapped_column(ForeignKey("risk_results.id"), nullable=False)
    risk_result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_result_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    output_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    plan_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_review")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    clinic: Mapped[Clinic] = relationship(foreign_keys=[clinic_id])
    patient: Mapped[Patient] = relationship(foreign_keys=[patient_id])
    generator: Mapped[User | None] = relationship(foreign_keys=[generated_by])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        UniqueConstraint("patient_id", "plan_version", name="uq_ai_treatment_plan_patient_version"),
        Index("idx_ai_treatment_plan_latest", "clinic_id", "patient_id", "plan_version"),
        Index(
            "idx_ai_treatment_plan_snapshot",
            "clinic_id",
            "patient_id",
            "case_snapshot_version",
            "input_digest",
        ),
    )


__all__ = ["AITreatmentPlanRecord"]
