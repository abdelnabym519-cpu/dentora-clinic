"""Append-only Case Intelligence persistence."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


class CaseSnapshotRecord(Base):
    """Immutable materialized snapshot of authoritative source state."""

    __tablename__ = "case_intelligence_snapshots"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    clinic: Mapped[Clinic] = relationship()
    patient: Mapped[Patient] = relationship(foreign_keys=[patient_id])
    generator: Mapped[User | None] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "clinic_id"],
            ["patients.id", "patients.clinic_id"],
            name="fk_case_intelligence_patient_clinic",
        ),
        UniqueConstraint(
            "patient_id",
            "snapshot_version",
            name="uq_case_intelligence_patient_snapshot_version",
        ),
        Index(
            "idx_case_intelligence_latest",
            "clinic_id",
            "patient_id",
            "snapshot_version",
        ),
        Index(
            "idx_case_intelligence_source_digest",
            "clinic_id",
            "patient_id",
            "source_digest",
        ),
    )


__all__ = ["CaseSnapshotRecord"]
