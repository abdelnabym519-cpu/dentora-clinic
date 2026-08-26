"""Versioned contracts for the advisory Clinical Copilot surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CLINICAL_COPILOT_CONTRACT_VERSION = "1.0"
CLINICAL_COPILOT_INPUT_VERSION = "1.0"
CLINICAL_COPILOT_PROMPT_VERSION = "1.0"
CLINICAL_COPILOT_SECOND_REVIEW_GATE_VERSION = "integrated-second-review/1.0"
PROVIDER_CONTRACT_VERSION = "core.llm.Provider/1"


class ClinicalCopilotRequest(BaseModel):
    """Finite, non-free-text intents keep cloud input inside the structured privacy boundary."""

    model_config = ConfigDict(extra="forbid")

    focus: Literal[
        "case_review",
        "risk_context",
        "treatment_options",
        "simulation_context",
        "second_review",
    ] = "case_review"


class ClinicalCopilotLimitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, max_length=100)
    status: Literal["not_available", "invalid_or_stale"]
    reason: str | None = Field(default=None, max_length=500)


class ClinicalCopilotClaim(BaseModel):
    """One advisory statement with explicit references into reviewed workflow artifacts."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_factor_ids: list[str] = Field(default_factory=list)
    planning_option_ids: list[str] = Field(default_factory=list)
    simulation_checkpoint_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _traceable(self) -> ClinicalCopilotClaim:
        if not (
            self.evidence_ids
            or self.risk_factor_ids
            or self.planning_option_ids
            or self.simulation_checkpoint_ids
        ):
            raise ValueError("clinical_copilot_claim_requires_traceability")
        return self


class ClinicalCopilotContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2400)
    claims: list[ClinicalCopilotClaim] = Field(default_factory=list, max_length=20)
    limitations: list[ClinicalCopilotLimitation] = Field(default_factory=list)
    questions_for_dentist: list[str] = Field(default_factory=list, max_length=12)
    advisory_only: Literal[True] = True
    dentist_review_required: Literal[True] = True
    autonomous_diagnosis: Literal[False] = False
    autonomous_treatment_decision: Literal[False] = False
    canonical_record_mutation: Literal[False] = False


class ClinicalCopilotWorkflowReference(BaseModel):
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
    simulation_id: UUID
    simulation_version: int = Field(ge=1)
    simulation_input_digest: str
    simulation_output_digest: str
    simulation_option_id: str
    second_review_gate_version: str = CLINICAL_COPILOT_SECOND_REVIEW_GATE_VERSION
    second_review_gate_digest: str


class ClinicalCopilotModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    provider_contract_version: str = PROVIDER_CONTRACT_VERSION
    prompt_version: str = CLINICAL_COPILOT_PROMPT_VERSION
    input_contract_version: str = CLINICAL_COPILOT_INPUT_VERSION
    input_digest: str
    output_digest: str


class ClinicalCopilotResult(BaseModel):
    """Ephemeral advisory artifact; it never creates or updates canonical clinical records."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CLINICAL_COPILOT_CONTRACT_VERSION
    patient_id: UUID
    focus: str
    content: ClinicalCopilotContent
    workflow: ClinicalCopilotWorkflowReference
    provenance: ClinicalCopilotModelProvenance
    generated_at: datetime
    generated_by: UUID
    advisory_only: Literal[True] = True
    dentist_controlled: Literal[True] = True
    creates_or_updates_clinical_records: Literal[False] = False
    disclaimer: Literal[
        "Advisory clinical decision support only; the dentist remains responsible for diagnosis and treatment decisions."
    ] = (
        "Advisory clinical decision support only; the dentist remains responsible for diagnosis "
        "and treatment decisions."
    )
