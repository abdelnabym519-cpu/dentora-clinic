"""Versioned contracts for advisory AI Second Review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AI_SECOND_REVIEW_CONTRACT_VERSION = "1.0"
AI_SECOND_REVIEW_INPUT_VERSION = "1.0"
AI_SECOND_REVIEW_PROMPT_VERSION = "1.0"
PROVIDER_CONTRACT_VERSION = "core.llm.Provider/1"


class SecondReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"


class FindingCategory(StrEnum):
    EVIDENCE_TRACEABILITY = "evidence_traceability"
    RISK_CONTEXT = "risk_context"
    PLANNING_CONSISTENCY = "planning_consistency"
    SIMULATION_CONSISTENCY = "simulation_consistency"
    SAFETY_BOUNDARY = "safety_boundary"


class SecondReviewFinding(BaseModel):
    """One advisory discrepancy or review point grounded in existing artifacts."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1, max_length=40)
    category: FindingCategory
    statement: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_factor_ids: list[str] = Field(default_factory=list)
    planning_refs: list[str] = Field(default_factory=list)
    simulation_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _requires_traceable_reference(self) -> SecondReviewFinding:
        if not any(
            (
                self.evidence_ids,
                self.risk_factor_ids,
                self.planning_refs,
                self.simulation_refs,
            )
        ):
            raise ValueError("second_review_finding_requires_traceable_reference")
        return self


class SecondReviewDataGap(BaseModel):
    """Explicit missing/stale source state copied from Case Intelligence."""

    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, max_length=100)
    status: Literal["not_available", "invalid_or_stale"]
    reason: str | None = Field(default=None, max_length=500)


class SecondReviewContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_SECOND_REVIEW_CONTRACT_VERSION
    advisory_only: Literal[True] = True
    no_treatment_approval: Literal[True] = True
    no_canonical_record_mutation: Literal[True] = True
    findings: list[SecondReviewFinding] = Field(default_factory=list, max_length=30)
    data_gaps: list[SecondReviewDataGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_finding_ids(self) -> SecondReviewContent:
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("duplicate_second_review_finding_id")
        return self


class SecondReviewChainReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    case_source_digest: str
    risk_engine_version: str
    risk_policy_version: str
    risk_input_digest: str
    risk_result_digest: str
    planning_id: UUID
    planning_version: int = Field(ge=1)
    planning_output_digest: str
    planning_reviewed_at: datetime
    planning_reviewed_by: UUID
    option_id: str
    simulation_id: UUID
    simulation_version: int = Field(ge=1)
    simulation_engine_version: str
    simulation_input_digest: str
    simulation_output_digest: str


class ModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    provider_contract_version: str = PROVIDER_CONTRACT_VERSION
    prompt_version: str = AI_SECOND_REVIEW_PROMPT_VERSION
    input_contract_version: str = AI_SECOND_REVIEW_INPUT_VERSION
    input_digest: str
    output_digest: str


class AISecondReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: UUID


class DentistReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed: Literal[True] = True


class AISecondReviewResult(BaseModel):
    """Append-only advisory second-review artifact; never a treatment approval."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    review_version: int = Field(ge=1)
    contract_version: str = AI_SECOND_REVIEW_CONTRACT_VERSION
    chain_reference: SecondReviewChainReference
    content: SecondReviewContent
    provenance: ModelProvenance
    review_status: SecondReviewStatus
    clinical_output: bool
    approves_treatment: Literal[False] = False
    mutates_canonical_records: Literal[False] = False
    generated_at: datetime
    generated_by: UUID | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    disclaimer: Literal[
        "Advisory consistency review only; it does not approve treatment and requires dentist review before clinical use."
    ] = (
        "Advisory consistency review only; it does not approve treatment and requires dentist "
        "review before clinical use."
    )
