"""Versioned AI Case Summary contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AI_CASE_SUMMARY_CONTRACT_VERSION = "1.0"
AI_CASE_SUMMARY_PROMPT_VERSION = "1.0"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SummaryClaim(BaseModel):
    """One advisory observed-fact claim with mandatory evidence aliases."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1)


class SummaryDataGap(BaseModel):
    """Explicit unavailable/stale source state; never a fabricated clinical fact."""

    model_config = ConfigDict(extra="forbid")

    section: str
    status: Literal["not_available", "invalid_or_stale"]
    reason: str | None = None


class SummaryContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_CASE_SUMMARY_CONTRACT_VERSION
    advisory_only: Literal[True] = True
    claims: list[SummaryClaim] = Field(default_factory=list)
    data_gaps: list[SummaryDataGap] = Field(default_factory=list)


class UnifiedCaseReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    case_source_digest: str


class ModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    provider_contract_version: str
    prompt_version: str
    input_digest: str
    output_digest: str


class AICaseSummary(BaseModel):
    """Persisted summary. It is clinical output only after dentist acceptance."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    summary_version: int = Field(ge=1)
    contract_version: str = AI_CASE_SUMMARY_CONTRACT_VERSION
    unified_case: UnifiedCaseReference
    content: SummaryContent
    provenance: ModelProvenance
    review_status: ReviewStatus
    clinical_output: bool
    generated_at: datetime
    generated_by: UUID | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
