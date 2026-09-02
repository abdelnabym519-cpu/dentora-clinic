"""Pathology detection models — analysis snapshot + per-finding rows.

Follows the periodontogram pattern: one immutable ``PathologyAnalysis``
per run plus child ``PathologyFinding`` rows for the detected
abnormalities. The source image is referenced by ``document_id`` as a
plain UUID (no FK) — the module reads the media ``Document`` at
analysis time and stays uninstallable even if ``media`` is removed.

``summary`` is a frozen JSONB blob (per-diagnosis counts) so list
endpoints never need to aggregate child rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

from .constants import ANALYSIS_STATUSES, DIAGNOSES

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


class PathologyAnalysis(Base, TimestampMixin):
    """One AI run against one patient image."""

    __tablename__ = "pathology_analyses"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    patient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )

    # Plain UUID — read-only coupling to the media module (see module doc).
    document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(12), nullable=False)
    engine: Mapped[str | None] = mapped_column(String(40))
    model_version: Mapped[str | None] = mapped_column(String(80))

    # Original image geometry needed to render normalized boxes.
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)

    findings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inference_ms: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict | None] = mapped_column(JSONB)

    notes: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    clinic: Mapped[Clinic] = relationship()
    patient: Mapped[Patient] = relationship()
    recorder: Mapped[User] = relationship(foreign_keys=[created_by])
    findings: Mapped[list[PathologyFinding]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="PathologyFinding.quadrant, PathologyFinding.position, PathologyFinding.diagnosis",
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in ANALYSIS_STATUSES)})",
            name="ck_pathology_analysis_status",
        ),
        Index("ix_pathology_analysis_patient_status", "patient_id", "status"),
    )


class PathologyFinding(Base, TimestampMixin):
    """A single detected abnormality belonging to an analysis."""

    __tablename__ = "pathology_findings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pathology_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    diagnosis: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # Normalized [0,1] box.
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # FDI placement from the geometric enumeration step.
    tooth_number: Mapped[int | None] = mapped_column(Integer)
    quadrant: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)

    analysis: Mapped[PathologyAnalysis] = relationship(back_populates="findings")

    __table_args__ = (
        CheckConstraint(
            f"diagnosis IN ({', '.join(repr(d) for d in DIAGNOSES)})",
            name="ck_pathology_finding_diagnosis",
        ),
    )
