"""Dental 3D module database models.

Phase 1 persists exactly one row per patient: the latest persisted
``DentalScene`` (per-tooth view state + provenance). Teeth themselves
are **not** modelled relationally here — the tooth universe (FDI
notation, conditions, treatments) already belongs to the odontogram
module and is only read. See ADR 0018 for the trade-off rationale.
"""

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


class DentalScene(Base, TimestampMixin):
    """Persisted 3D scene state for one patient.

    ``teeth`` holds a list of :class:`app.modules.dental_3d.schemas.Tooth3D`
    dicts (validated by Pydantic at the service boundary). ``generator``
    records where the geometry came from — ``synthetic`` in Phase 1,
    reserved for future sources (segmentation, cbct, intraoral_scan,
    face_scan, digital_twin). ``segmentation`` is a nullable placeholder
    for the future automatic tooth-segmentation result; always ``None``
    while that capability does not exist.
    """

    __tablename__ = "dental_scenes"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    generator: Mapped[str] = mapped_column(String(30), default="synthetic")
    # Soft delete per repo convention (never hard-delete patient data).
    status: Mapped[str] = mapped_column(String(20), default="active")

    teeth: Mapped[list] = mapped_column(JSONB, default=list)
    segmentation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    patient: Mapped["Patient"] = relationship()
    creator: Mapped["User | None"] = relationship()

    __table_args__ = (
        UniqueConstraint("patient_id", name="uq_dental_scene_patient"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_dental_scene_status"),
        CheckConstraint(
            "generator IN ('synthetic', 'segmentation', 'cbct', "
            "'intraoral_scan', 'face_scan', 'digital_twin')",
            name="ck_dental_scene_generator",
        ),
        Index("idx_dental_scenes_clinic_patient", "clinic_id", "patient_id"),
    )


__all__ = ["DentalScene"]
