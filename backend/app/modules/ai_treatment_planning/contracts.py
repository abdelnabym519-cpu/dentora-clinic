"""Versioned contracts for advisory AI Treatment Planning."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AI_TREATMENT_PLANNING_CONTRACT_VERSION = "1.0"
AI_TREATMENT_PLANNING_INPUT_VERSION = "1.0"
AI_TREATMENT_PLANNING_PROMPT_VERSION = "1.0"
PROVIDER_CONTRACT_VERSION = "core.llm.Provider/1"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PlanningStep(BaseModel):
    """One advisory action in an option, grounded in known evidence."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=1000)
    purpose: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(min_length=1)
    risk_factor_ids: list[str] = Field(default_factory=list)


class TreatmentOption(BaseModel):
    """A candidate strategy for dentist consideration, never an autonomous order."""

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=240)
    clinical_intent: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(min_length=1)
    risk_factor_ids: list[str] = Field(default_factory=list)
    steps: list[PlanningStep] = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    alternatives_or_tradeoffs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _unique_step_ids(self) -> TreatmentOption:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate_step_id")
        return self


class PlanningDataGap(BaseModel):
    """Explicit source limitation copied from CaseSnapshot availability semantics."""

    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, max_length=100)
    status: Literal["not_available", "invalid_or_stale"]
    reason: str | None = Field(default=None, max_length=500)


class PlanningContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_TREATMENT_PLANNING_CONTRACT_VERSION
    advisory_only: Literal[True] = True
    no_automatic_execution: Literal[True] = True
    options: list[TreatmentOption] = Field(default_factory=list, max_length=8)
    data_gaps: list[PlanningDataGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_option_ids(self) -> PlanningContent:
        option_ids = [option.option_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("duplicate_option_id")
        return self


class PlanningCaseReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    case_source_digest: str
    risk_engine_version: str
    risk_policy_version: str
    risk_input_digest: str
    risk_result_digest: str
    risk_availability_state: Literal["available", "partial", "unavailable", "invalid_or_stale"]


class ModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    provider_contract_version: str = PROVIDER_CONTRACT_VERSION
    prompt_version: str = AI_TREATMENT_PLANNING_PROMPT_VERSION
    input_contract_version: str = AI_TREATMENT_PLANNING_INPUT_VERSION
    input_digest: str
    output_digest: str


class AITreatmentPlanningResult(BaseModel):
    """Append-only planning artifact; acceptance still does not mutate treatment_plan."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    planning_version: int = Field(ge=1)
    contract_version: str = AI_TREATMENT_PLANNING_CONTRACT_VERSION
    case_reference: PlanningCaseReference
    content: PlanningContent
    provenance: ModelProvenance
    review_status: ReviewStatus
    clinical_output: bool
    canonical_treatment_plan_created: Literal[False] = False
    generated_at: datetime
    generated_by: UUID | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    disclaimer: Literal[
        "Advisory treatment-planning support only; dentist review is required and no canonical plan is created automatically."
    ] = (
        "Advisory treatment-planning support only; dentist review is required and no canonical "
        "plan is created automatically."
    )


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
