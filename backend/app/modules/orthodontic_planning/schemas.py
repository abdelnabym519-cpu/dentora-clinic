"""Pydantic schemas for the orthodontic planning API.

All measurement bounds mirror the DB CHECK constraints and the
deterministic clinical constants — an assessment that violates a range
is rejected at the API boundary (defense in depth: the constraint
layer re-checks everything at plan time).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .constants import (
    GROWTH_STAGES,
    MAX_OVERJET_REDUCTION_MM,
    MAX_STAGES,
    MIN_CHARTED_PERMANENT_TEETH,
    MOLAR_DISTALIZATION_MAX_PER_SIDE_MM,
    MOVEMENT_LIMITS,
    OBJECTIVES,
    RELATIONS,
    REVIEW_DECISIONS,
    SKELETAL_PATTERNS,
    TARGET_OVERJET_MM,
)

ReviewDecision = Literal["approved", "rejected"]


# --- Requests ------------------------------------------------------------------


class AssessmentCreate(BaseModel):
    """Clinician-entered measurements. Fields are optional at creation
    (an under-documented case may be saved), but plan generation fails
    closed until every required field is present."""

    skeletal_pattern: Literal[SKELETAL_PATTERNS] | None = None  # type: ignore[valid-type]
    growth_stage: Literal[GROWTH_STAGES] | None = None  # type: ignore[valid-type]
    overjet_mm: float | None = Field(default=None, ge=-10.0, le=15.0)
    overbite_mm: float | None = Field(default=None, ge=-10.0, le=15.0)
    crowding_upper_mm: float | None = Field(default=None, ge=0.0, le=20.0)
    crowding_lower_mm: float | None = Field(default=None, ge=0.0, le=20.0)
    molar_relation_left: Literal[RELATIONS] | None = None  # type: ignore[valid-type]
    molar_relation_right: Literal[RELATIONS] | None = None  # type: ignore[valid-type]
    canine_relation_left: Literal[RELATIONS] | None = None  # type: ignore[valid-type]
    canine_relation_right: Literal[RELATIONS] | None = None  # type: ignore[valid-type]
    posterior_crossbite: bool = False
    objectives: list[Literal[OBJECTIVES]] = Field(default_factory=list)  # type: ignore[valid-type]
    notes: str | None = Field(default=None, max_length=4000)


class PlanCreate(BaseModel):
    """Body of POST /assessments/{id}/plan (reserved for future options
    such as provider override; the provider is server-configured)."""

    notes: str | None = Field(default=None, max_length=4000)


class ProposalReview(BaseModel):
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=4000)


# --- Responses ------------------------------------------------------------------


class MovementDTO(BaseModel):
    tooth: int
    movement_type: str
    magnitude: float


class StageDTO(BaseModel):
    label: str
    movements: list[MovementDTO]


class ConstraintViolationDTO(BaseModel):
    code: str
    severity: str
    message: str
    tooth: int | None = None


class ConstraintReportDTO(BaseModel):
    is_valid: bool
    hard_count: int
    soft_count: int
    violations: list[ConstraintViolationDTO]


class CapabilitiesResponse(BaseModel):
    provider: str
    provider_version: str
    constraints_version: str
    decision_support_only: bool
    deterministic: bool
    approval_required: bool
    planned_months_per_stage_weeks: int
    required_measurements: list[str]
    min_charted_permanent_teeth: int
    movement_limits: dict[str, dict[str, float]]
    envelopes: dict[str, float]


class AssessmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    skeletal_pattern: str | None
    growth_stage: str | None
    overjet_mm: float | None
    overbite_mm: float | None
    crowding_upper_mm: float | None
    crowding_lower_mm: float | None
    posterior_crossbite: bool
    objectives: list[str] | None
    is_plannable: bool
    created_at: datetime


class AssessmentDetail(AssessmentSummary):
    molar_relation_left: str | None
    molar_relation_right: str | None
    canine_relation_left: str | None
    canine_relation_right: str | None
    dentition_snapshot: dict
    data_sufficiency: dict
    notes: str | None
    created_by: UUID


class ProposalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    assessment_id: UUID
    provider: str
    provider_version: str
    constraints_version: str
    status: str
    stage_count: int
    planned_months: int
    score: float
    confidence: float
    hard_violation_count: int
    soft_finding_count: int
    created_at: datetime


class ProposalDetail(ProposalSummary):
    stages: list[StageDTO]
    constraint_report: ConstraintReportDTO
    uncertainty: list[str] | None
    rationale: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_by: UUID


class ProposalReviewResponse(BaseModel):
    id: UUID
    status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None


# --- Capability payload helpers ---------------------------------------------------

CAPABILITIES_ENVELOPES: dict[str, float] = {
    "target_overjet_mm": TARGET_OVERJET_MM,
    "max_overjet_reduction_mm": MAX_OVERJET_REDUCTION_MM,
    "max_upper_proclination_mm": 3.0,
    "max_lower_proclination_mm": 2.0,
    "molar_distalization_max_per_side_mm": MOLAR_DISTALIZATION_MAX_PER_SIDE_MM,
    "max_stages": float(MAX_STAGES),
}


def assessment_summary(a) -> AssessmentSummary:
    """Summary projection (sufficiency flattened for list views)."""
    sufficiency = a.data_sufficiency or {}
    return AssessmentSummary(
        id=a.id,
        patient_id=a.patient_id,
        skeletal_pattern=a.skeletal_pattern,
        growth_stage=a.growth_stage,
        overjet_mm=a.overjet_mm,
        overbite_mm=a.overbite_mm,
        crowding_upper_mm=a.crowding_upper_mm,
        crowding_lower_mm=a.crowding_lower_mm,
        posterior_crossbite=bool(a.posterior_crossbite),
        objectives=a.objectives or [],
        is_plannable=bool(sufficiency.get("is_plannable", False)),
        created_at=a.created_at,
    )


def assessment_detail(a) -> AssessmentDetail:
    """Detail projection (adds snapshot + sufficiency + review-relevant
    fields; ``is_plannable`` is derived, hence the manual build)."""
    return AssessmentDetail(
        **assessment_summary(a).model_dump(),
        molar_relation_left=a.molar_relation_left,
        molar_relation_right=a.molar_relation_right,
        canine_relation_left=a.canine_relation_left,
        canine_relation_right=a.canine_relation_right,
        dentition_snapshot=a.dentition_snapshot or {},
        data_sufficiency=a.data_sufficiency or {},
        notes=a.notes,
        created_by=a.created_by,
    )


__all__ = [
    "AssessmentCreate",
    "AssessmentDetail",
    "AssessmentSummary",
    "CapabilitiesResponse",
    "CAPABILITIES_ENVELOPES",
    "ConstraintReportDTO",
    "ConstraintViolationDTO",
    "MOVEMENT_LIMITS",
    "MIN_CHARTED_PERMANENT_TEETH",
    "MovementDTO",
    "PlanCreate",
    "ProposalDetail",
    "ProposalReview",
    "ProposalReviewResponse",
    "ProposalSummary",
    "REVIEW_DECISIONS",
    "StageDTO",
    "assessment_summary",
]
