"""Orthodontic planning models — assessment snapshot + plan proposal.

Two immutable-by-convention rows per clinical act, mirroring the
periodontogram/pathology pattern:

* ``OrthoAssessment`` — clinician-entered measurements + an immutable
  JSONB dentition snapshot copied (read-only) from the odontogram at
  creation time. No FK to odontogram tables: the module reads
  ``tooth_records`` only while building the snapshot, so uninstall
  stays clean.
* ``OrthoPlanProposal`` — one planner run. Provider output is stored
  verbatim (stages JSONB) *together with* the deterministic constraint
  report and uncertainty notes, so a reviewer always sees the plan and
  its safety envelope side by side. Proposals never write anywhere
  else — consuming an approved proposal into a treatment plan is a
  separate, manual clinical act outside this module.

Decision-support posture: a proposal is only ever a *document*.
``status`` moves draft → approved/rejected exclusively through an
explicit clinician review endpoint (audited via events); no code path
in this module can execute a plan autonomously.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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

from .constants import (
    CONSTRAINTS_VERSION,
    GROWTH_STAGES,
    PROPOSAL_STATUSES,
    RELATIONS,
    SKELETAL_PATTERNS,
)

if TYPE_CHECKING:
    from app.core.auth.models import Clinic, User
    from app.modules.patients.models import Patient


def _enum_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IN ({', '.join(repr(v) for v in values)}) OR {column} IS NULL",
        name=name,
    )


class OrthoAssessment(Base, TimestampMixin):
    """One clinician-entered orthodontic case assessment."""

    __tablename__ = "ortho_assessments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    patient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Clinician-entered measurements (Float mm / enum codes; see constants).
    skeletal_pattern: Mapped[str | None] = mapped_column(String(12))
    growth_stage: Mapped[str | None] = mapped_column(String(12))
    overjet_mm: Mapped[float | None] = mapped_column(Float)
    overbite_mm: Mapped[float | None] = mapped_column(Float)
    crowding_upper_mm: Mapped[float | None] = mapped_column(Float)
    crowding_lower_mm: Mapped[float | None] = mapped_column(Float)
    molar_relation_left: Mapped[str | None] = mapped_column(String(12))
    molar_relation_right: Mapped[str | None] = mapped_column(String(12))
    canine_relation_left: Mapped[str | None] = mapped_column(String(12))
    canine_relation_right: Mapped[str | None] = mapped_column(String(12))
    posterior_crossbite: Mapped[bool] = mapped_column(Boolean, default=False)
    objectives: Mapped[list | None] = mapped_column(JSONB)

    # Immutable copy of the odontogram state at assessment time.
    dentition_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {"is_plannable": bool, "missing": [...], "score": float, "charted_permanent": int}
    data_sufficiency: Mapped[dict] = mapped_column(JSONB, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)

    clinic: Mapped[Clinic] = relationship()
    patient: Mapped[Patient] = relationship()
    recorder: Mapped[User] = relationship(foreign_keys=[created_by])
    proposals: Mapped[list[OrthoPlanProposal]] = relationship(back_populates="assessment")

    __table_args__ = (
        _enum_check("skeletal_pattern", SKELETAL_PATTERNS, "ck_ortho_assessment_skeletal"),
        _enum_check("growth_stage", GROWTH_STAGES, "ck_ortho_assessment_growth"),
        _enum_check("molar_relation_left", RELATIONS, "ck_ortho_assessment_molar_l"),
        _enum_check("molar_relation_right", RELATIONS, "ck_ortho_assessment_molar_r"),
        _enum_check("canine_relation_left", RELATIONS, "ck_ortho_assessment_canine_l"),
        _enum_check("canine_relation_right", RELATIONS, "ck_ortho_assessment_canine_r"),
        CheckConstraint(
            "(overjet_mm IS NULL) OR (overjet_mm BETWEEN -10 AND 15)",
            name="ck_ortho_assessment_overjet",
        ),
        CheckConstraint(
            "(overbite_mm IS NULL) OR (overbite_mm BETWEEN -10 AND 15)",
            name="ck_ortho_assessment_overbite",
        ),
        CheckConstraint(
            "(crowding_upper_mm IS NULL) OR (crowding_upper_mm BETWEEN 0 AND 20)",
            name="ck_ortho_assessment_crowding_upper",
        ),
        CheckConstraint(
            "(crowding_lower_mm IS NULL) OR (crowding_lower_mm BETWEEN 0 AND 20)",
            name="ck_ortho_assessment_crowding_lower",
        ),
        Index("ix_ortho_assessment_patient_created", "patient_id", "created_at"),
    )


class OrthoPlanProposal(Base, TimestampMixin):
    """One planner run: proposed staged movements + deterministic safety
    report + uncertainty, awaiting (or recording) clinician review."""

    __tablename__ = "ortho_plan_proposals"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    clinic_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clinics.id"), nullable=False, index=True
    )
    patient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    assessment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ortho_assessments.id"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Provenance (which policy produced this, under which bound set).
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(40), nullable=False)
    constraints_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default=CONSTRAINTS_VERSION
    )

    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")

    stage_count: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)

    # Provider output + independent deterministic gate + uncertainty, verbatim.
    stages: Mapped[dict] = mapped_column(JSONB, nullable=False)
    constraint_report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    uncertainty: Mapped[list | None] = mapped_column(JSONB)

    # Clinician review (the only path out of ``draft``).
    reviewed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

    clinic: Mapped[Clinic] = relationship()
    patient: Mapped[Patient] = relationship()
    assessment: Mapped[OrthoAssessment] = relationship(back_populates="proposals")
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in PROPOSAL_STATUSES)})",
            name="ck_ortho_proposal_status",
        ),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_ortho_proposal_score"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_ortho_proposal_confidence"),
        Index("ix_ortho_proposal_patient_status", "patient_id", "status"),
    )
