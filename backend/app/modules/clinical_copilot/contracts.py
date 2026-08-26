"""Versioned contracts for the advisory-only Clinical Copilot surface."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CLINICAL_COPILOT_CONTRACT_VERSION = "1.0"


class StageName(StrEnum):
    CASE_INTELLIGENCE = "case_intelligence"
    RISK_ENGINE = "risk_engine"
    TREATMENT_PLANNING = "ai_treatment_planning"
    TREATMENT_SIMULATION = "treatment_simulation"
    AI_SECOND_REVIEW = "ai_second_review"


class StageState(StrEnum):
    READY = "ready"
    MISSING = "missing"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class ClinicalStageStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: StageName
    state: StageState
    artifact_id: str | None = None
    artifact_version: int | None = None
    generated_at: datetime | None = None
    source_digest: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str | None = None


class ClinicalCopilotContext(BaseModel):
    """Read-only evidence chain presented to the dentist before any advice is generated."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CLINICAL_COPILOT_CONTRACT_VERSION
    clinic_id: UUID
    patient_id: UUID
    stages: list[ClinicalStageStatus]
    missing_or_stale: list[str] = Field(default_factory=list)
    evidence_catalog: dict[str, dict[str, Any]] = Field(default_factory=dict)
    input_digest: str
    ready_for_advice: bool
    advisory_only: bool = True
    dentist_control_required: bool = True
    canonical_record_mutation: bool = False


class ClinicalCopilotAsk(BaseModel):
    patient_id: UUID
    question: str = Field(min_length=1, max_length=4000)


class AdvisoryClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class ClinicalCopilotProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    contract_version: str = CLINICAL_COPILOT_CONTRACT_VERSION
    input_digest: str
    generated_at: datetime


class ClinicalCopilotAdvisory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID
    claims: list[AdvisoryClaim]
    limitations: list[str] = Field(default_factory=list)
    provenance: ClinicalCopilotProvenance
    advisory_only: bool = True
    dentist_review_required: bool = True
    autonomous_diagnosis: bool = False
    autonomous_treatment_decision: bool = False
    canonical_record_mutation: bool = False
