"""Versioned AI Treatment Planning contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AI_TREATMENT_PLAN_CONTRACT_VERSION = "1.0"
AI_TREATMENT_PLAN_PROMPT_VERSION = "1.0"


class TreatmentReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TreatmentPlanStep(BaseModel):
    """One advisory step grounded in explicit CaseSnapshot evidence."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)


class TreatmentPlanOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=240)
    intent: str = Field(min_length=1, max_length=600)
    steps: list[TreatmentPlanStep] = Field(min_length=1, max_length=30)


class TreatmentDataGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    status: Literal["not_available", "invalid_or_stale"]
    reason: str | None = None


class TreatmentPlanContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_TREATMENT_PLAN_CONTRACT_VERSION
    advisory_only: Literal[True] = True
    options: list[TreatmentPlanOption] = Field(default_factory=list, max_length=8)
    data_gaps: list[TreatmentDataGap] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class TreatmentPlanningInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    case_source_digest: str
    summary_id: UUID
    summary_version: int = Field(ge=1)
    summary_output_digest: str
    risk_result_id: UUID
    risk_result_version: int = Field(ge=1)
    risk_result_digest: str


class TreatmentModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    provider_contract_version: str
    prompt_version: str
    input_digest: str
    output_digest: str


class AITreatmentPlan(BaseModel):
    """Persisted advisory draft; never mutates the canonical treatment plan."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    plan_version: int = Field(ge=1)
    contract_version: str = AI_TREATMENT_PLAN_CONTRACT_VERSION
    inputs: TreatmentPlanningInputs
    content: TreatmentPlanContent
    provenance: TreatmentModelProvenance
    review_status: TreatmentReviewStatus
    clinical_output: bool
    generated_at: datetime
    generated_by: UUID | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    requires_dentist_review: Literal[True] = True
    applied_to_treatment_plan: Literal[False] = False
    disclaimer: Literal[
        "Advisory treatment-planning draft only; dentist review and independent clinical judgment are required."
    ] = (
        "Advisory treatment-planning draft only; dentist review and independent clinical judgment are required."
    )


class TreatmentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
