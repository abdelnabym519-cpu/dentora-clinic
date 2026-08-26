"""Append-only persistence for Treatment Simulation artifacts."""

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
    from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord
    from app.modules.patients.models import Patient


class TreatmentSimulationRecord(Base):
    __tablename__ = "treatment_simulation_results"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    simulation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    planning_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_treatment_planning_results.id"), nullable=False, index=True
    )
    planning_version: Mapped[int] = mapped_column(Integer, nullable=False)
    planning_output_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    planning_reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planning_reviewed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    option_id: Mapped[str] = mapped_column(String(40), nullable=False)
    case_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    case_snapshot_contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    case_source_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    risk_engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    risk_input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    risk_result_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    output_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    scene_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    clinic: Mapped[Clinic] = relationship(foreign_keys=[clinic_id])
    patient: Mapped[Patient] = relationship(foreign_keys=[patient_id])
    planning: Mapped[AITreatmentPlanningRecord] = relationship(foreign_keys=[planning_id])
    generator: Mapped[User | None] = relationship(foreign_keys=[generated_by])
    planning_reviewer: Mapped[User] = relationship(foreign_keys=[planning_reviewed_by])

    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "simulation_version",
            name="uq_treatment_simulation_patient_version",
        ),
        Index(
            "idx_treatment_simulation_latest",
            "clinic_id",
            "patient_id",
            "simulation_version",
        ),
        Index(
            "idx_treatment_simulation_input",
            "clinic_id",
            "patient_id",
            "input_digest",
        ),
        Index(
            "idx_treatment_simulation_plan",
            "clinic_id",
            "patient_id",
            "planning_id",
            "option_id",
        ),
    )


__all__ = ["TreatmentSimulationRecord"]
