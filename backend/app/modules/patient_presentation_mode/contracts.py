"""Versioned contracts for Patient Presentation Mode."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PATIENT_PRESENTATION_CONTRACT_VERSION = "1.0"


class PresentationClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1)


class PresentationDataGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    status: Literal["not_available", "invalid_or_stale"]
    reason: str | None = None


class PresentationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_summary_id: UUID
    source_summary_version: int = Field(ge=1)
    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    case_source_digest: str = Field(min_length=1)
    reviewed_at: datetime
    reviewed_by: UUID
    provider: str
    model: str
    input_digest: str = Field(min_length=1)
    output_digest: str = Field(min_length=1)


class PatientPresentation(BaseModel):
    """Ephemeral, read-only projection of dentist-accepted clinical output."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = PATIENT_PRESENTATION_CONTRACT_VERSION
    mode: Literal["patient_presentation"] = "patient_presentation"
    patient_id: UUID
    advisory_only: Literal[True] = True
    dentist_controlled: Literal[True] = True
    source_current: Literal[True] = True
    claims: list[PresentationClaim] = Field(default_factory=list)
    data_gaps: list[PresentationDataGap] = Field(default_factory=list)
    provenance: PresentationProvenance
