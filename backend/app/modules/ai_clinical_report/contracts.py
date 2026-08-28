"""Versioned contracts for non-canonical AI Clinical Report drafts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.clinical_copilot.contracts import (
    AdvisoryClaim,
    ClinicalStageStatus,
    StageState,
)

AI_CLINICAL_REPORT_CONTRACT_VERSION = "1.0"


class ClinicalReportStatus(StrEnum):
    DRAFT = "draft"


class ReportSectionName(StrEnum):
    CASE_INTELLIGENCE = "case_intelligence"
    RISK_ENGINE = "risk_engine"
    TREATMENT_PLANNING = "ai_treatment_planning"
    TREATMENT_SIMULATION = "treatment_simulation"
    AI_SECOND_REVIEW = "ai_second_review"
    CROSS_STAGE = "cross_stage"


class AIClinicalReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID


class AIClinicalReportReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_CLINICAL_REPORT_CONTRACT_VERSION
    patient_id: UUID
    ready_for_report: bool
    stages: list[ClinicalStageStatus]
    missing_or_stale: list[str] = Field(default_factory=list)
    input_digest: str
    advisory_only: bool = True
    dentist_control_required: bool = True
    canonical_record_mutation: bool = False


class AIClinicalReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: ReportSectionName
    state: StageState | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    claims: list[AdvisoryClaim] = Field(default_factory=list)


class AIClinicalReportProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_CLINICAL_REPORT_CONTRACT_VERSION
    provider: str
    model: str
    source_advisory_input_digest: str
    source_advisory_output_digest: str
    report_output_digest: str
    upstream: list[ClinicalStageStatus]
    generated_at: datetime
    generated_by: UUID


class AIClinicalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AI_CLINICAL_REPORT_CONTRACT_VERSION
    patient_id: UUID
    status: ClinicalReportStatus = ClinicalReportStatus.DRAFT
    sections: list[AIClinicalReportSection]
    limitations: list[str] = Field(default_factory=list)
    provenance: AIClinicalReportProvenance
    advisory_only: bool = True
    dentist_review_required: bool = True
    autonomous_diagnosis: bool = False
    autonomous_treatment_decision: bool = False
    canonical_record_mutation: bool = False
