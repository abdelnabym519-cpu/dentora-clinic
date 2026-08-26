"""Append-only Risk Engine persistence; canonical clinical records remain untouched."""

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


class RiskResultRecord(Base):
    __tablename__ = "risk_results"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    case_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    case_snapshot_contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    result_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    availability_state: Mapped[str] = mapped_column(String(30), nullable=False)
    result_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
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
        UniqueConstraint("patient_id", "result_version", name="uq_risk_result_patient_version"),
        Index("idx_risk_result_latest", "clinic_id", "patient_id", "result_version"),
        Index(
            "idx_risk_result_snapshot",
            "clinic_id",
            "patient_id",
            "case_snapshot_version",
            "input_digest",
        ),
        Index("idx_risk_result_digest", "clinic_id", "patient_id", "result_digest"),
    )


__all__ = ["RiskResultRecord"]
