"""Dental 3D module database models.

Phase 1 persists exactly one row per patient: the latest persisted
``DentalScene`` (per-tooth view state + provenance). Teeth themselves
are **not** modelled relationally here — the tooth universe (FDI
notation, conditions, treatments) already belongs to the odontogram
module and is only read. See ADR 0018 for the trade-off rationale.

Phase 3 adds ``DentalSegmentationAnalysis``: persisted automatic tooth
segmentation analyses (per-tooth proposals + dentist review state).
Analyses are *decision support*, never clinical records — review
acceptance records the dentist's acknowledgement and never mutates
odontogram data. Uninstalling the module drops this table together
with the dental_3d Alembic branch (analyses are derivable, not source
data).

Phase 4 adds ``DentalNerveAnalysis``; Phase 5.2 evolves it to persist explicit
CBCT model outcomes, native-coordinate findings, provenance and safe failure
states. It remains append-only decision support and never represents patient
alignment, implant/surgical planning or a clinical record (ADR 0024).
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class DentalSegmentationAnalysis(Base, TimestampMixin):
    """One persisted automatic tooth-segmentation analysis (Phase 3).

    ``teeth`` holds a list of
    :class:`app.modules.dental_3d.segmentation.SegmentedTooth` dicts
    (validated by Pydantic at the service boundary — including FDI
    validity and confidence bounds). Rows are append-only history:
    running a new analysis inserts a new row; ``review_status`` records
    the dentist's decision on the latest one. ``provider``/``method``
    identify the engine — today the deterministic arch-partition
    adapter, tomorrow a real ML model behind the same port — and imply
    **no clinical claim** (ADR 0021).
    """

    __tablename__ = "dental_segmentation_analyses"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    performed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    provider: Mapped[str] = mapped_column(String(50))
    method: Mapped[str] = mapped_column(String(100))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    teeth: Mapped[list] = mapped_column(JSONB, default=list)

    #: Dentist review workflow: pending → accepted | rejected.
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    patient: Mapped["Patient"] = relationship()
    performer: Mapped["User | None"] = relationship(foreign_keys=[performed_by])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_dental_segmentation_review_status",
        ),
        Index(
            "idx_dental_segmentation_latest",
            "clinic_id",
            "patient_id",
            "created_at",
        ),
    )


class DentalNerveAnalysis(Base, TimestampMixin):
    """One persisted mandibular nerve-detection analysis (Phases 4/5.2).

    ``pathways`` holds a list of
    :class:`app.modules.dental_3d.nerve.NervePathway` dicts and
    ``proximities`` a list of ``ToothNerveProximity`` dicts (both
    validated by Pydantic at the service boundary). Rows are
    append-only history; ``review_status`` records the dentist's
    decision on the latest one. Phase 5.2 adds explicit outcomes, failure
    detail and provenance metadata for the CBCT model-service adapter.
    Native findings are non-clinical and never imply alignment or planning
    (ADR 0024).
    """

    __tablename__ = "dental_nerve_analyses"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    performed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    provider: Mapped[str] = mapped_column(String(50))
    method: Mapped[str] = mapped_column(String(100))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    pathways: Mapped[list] = mapped_column(JSONB, default=list)
    proximities: Mapped[list] = mapped_column(JSONB, default=list)

    detection_status: Mapped[str] = mapped_column(String(32), default="uncertain")
    input_kind: Mapped[str] = mapped_column(String(32), default="scene")
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    analysis_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

    #: Dentist review workflow, or not_applicable for an operational failure.
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Relationships
    clinic: Mapped["Clinic"] = relationship()
    patient: Mapped["Patient"] = relationship()
    performer: Mapped["User | None"] = relationship(foreign_keys=[performed_by])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'not_applicable')",
            name="ck_dental_nerve_review_status",
        ),
        CheckConstraint(
            "detection_status IN ('detected', 'no_detection', 'uncertain', 'failed')",
            name="ck_dental_nerve_detection_status",
        ),
        Index(
            "idx_dental_nerve_latest",
            "clinic_id",
            "patient_id",
            "created_at",
        ),
    )


class DentalAlignmentResult(Base, TimestampMixin):
    """Append-only patient-specific IOS→CBCT rigid registration result."""

    __tablename__ = "dental_alignment_results"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    performed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(20))
    algorithm: Mapped[str] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(255))
    transform: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_frame: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_frame: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    clinic: Mapped["Clinic"] = relationship()
    patient: Mapped["Patient"] = relationship()
    performer: Mapped["User | None"] = relationship(foreign_keys=[performed_by])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_review', 'accepted', 'rejected', 'failed', 'uncertain')",
            name="ck_dental_alignment_status",
        ),
        Index(
            "idx_dental_alignment_latest",
            "clinic_id",
            "patient_id",
            "created_at",
        ),
    )


__all__ = [
    "DentalAlignmentResult",
    "DentalNerveAnalysis",
    "DentalScene",
    "DentalSegmentationAnalysis",
]
