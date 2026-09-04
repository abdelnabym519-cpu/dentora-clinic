"""Pydantic contracts for the pathology detection API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DiagnosisLiteral = Literal["caries", "deep_caries", "periapical_lesion", "impacted_tooth"]
StatusLiteral = Literal["running", "completed", "failed"]


class AnalysisCreate(BaseModel):
    """Run an analysis on an existing media document."""

    document_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    diagnosis: DiagnosisLiteral
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: dict[str, float]
    tooth_number: int | None = Field(default=None, ge=11, le=48)
    quadrant: int | None = Field(default=None, ge=1, le=4)
    position: int | None = Field(default=None, ge=1, le=8)


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    document_id: UUID | None
    status: StatusLiteral
    engine: str | None
    model_version: str | None
    image_width: int | None
    image_height: int | None
    findings_count: int
    inference_ms: int | None
    summary: dict[str, int] | None
    notes: str | None
    created_by: UUID
    created_at: datetime


class AnalysisDetail(AnalysisSummary):
    error: str | None
    findings: list[FindingResponse] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    """Engine availability advertisement for the UI."""

    available: bool
    configured: bool
    engine: str
    model_version: str = ""
    reason: str | None = None
