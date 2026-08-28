"""Versioned deterministic Risk Engine contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RISK_RESULT_CONTRACT_VERSION = "1.0"
RISK_ENGINE_VERSION = "1.0.0"
RISK_POLICY_VERSION = "observed-facts-v1"


class RiskFactorState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_AVAILABLE = "not_available"
    INVALID_OR_STALE = "invalid_or_stale"


class RiskDisplayBand(StrEnum):
    EVIDENCE_PRESENT = "evidence_present"
    EVIDENCE_ABSENT = "evidence_absent"
    DATA_GAP = "data_gap"
    INVALID_SOURCE = "invalid_source"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RiskEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^E[0-9]{3,}$")
    source_module: str
    source_entity: str
    source_record_id: str | None = None
    source_version: str | None = None
    source_digest: str | None = None
    validation_state: str | None = None


class RiskFactor(BaseModel):
    """One explicit observed fact or data-gap state; never a diagnosis."""

    model_config = ConfigDict(extra="forbid")

    factor_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=240)
    state: RiskFactorState
    display_band: RiskDisplayBand
    evidence_ids: list[str] = Field(default_factory=list)
    observed_value: bool | float | int | str | None = None
    unit: str | None = Field(default=None, max_length=32)
    semantics: str = Field(min_length=1, max_length=500)


class PatientPointMm(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float
    y: float
    z: float


class PatientVector(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float
    y: float
    z: float


class RiskMapFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dicom_patient"] = "dicom_patient"
    unit: Literal["mm"] = "mm"
    frame_of_reference_uid: str = Field(min_length=1, max_length=128)


class RiskMapRegion(BaseModel):
    """Patient-space advisory display geometry linked to risk evidence."""

    model_config = ConfigDict(extra="forbid")

    region_id: str = Field(min_length=1, max_length=160)
    kind: Literal["polyline", "cylinder"]
    display_band: RiskDisplayBand
    factor_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    points: list[PatientPointMm] = Field(default_factory=list)
    center: PatientPointMm | None = None
    axis: PatientVector | None = None
    radius_mm: float | None = Field(default=None, gt=0)
    length_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _coherent_geometry(self) -> RiskMapRegion:
        if self.kind == "polyline":
            if len(self.points) < 2 or any(
                value is not None
                for value in (self.center, self.axis, self.radius_mm, self.length_mm)
            ):
                raise ValueError("polyline risk region requires points only")
        elif (
            self.center is None
            or self.axis is None
            or self.radius_mm is None
            or self.length_mm is None
            or self.points
        ):
            raise ValueError("cylinder risk region requires center/axis/radius/length only")
        return self


class RiskMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "unavailable"]
    frame: RiskMapFrame | None = None
    regions: list[RiskMapRegion] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=255)
    advisory_only: Literal[True] = True
    synthetic_geometry: Literal[False] = False

    @model_validator(mode="after")
    def _coherent(self) -> RiskMap:
        if self.status == "available":
            if self.frame is None or not self.regions:
                raise ValueError("available risk map requires frame and evidence regions")
        elif self.frame is not None or self.regions:
            raise ValueError("unavailable risk map cannot expose geometry")
        return self


class RiskProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_snapshot_version: int = Field(ge=1)
    case_snapshot_contract_version: str
    source_digest: str
    input_digest: str
    result_digest: str
    engine_version: str = RISK_ENGINE_VERSION
    policy_version: str = RISK_POLICY_VERSION
    generated_at: datetime
    availability_state: Literal["available", "partial", "unavailable", "invalid_or_stale"]


class RiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    result_version: int = Field(ge=1)
    contract_version: str = RISK_RESULT_CONTRACT_VERSION
    factors: list[RiskFactor]
    evidence: list[RiskEvidenceReference]
    risk_map: RiskMap
    provenance: RiskProvenance
    review_status: ReviewStatus
    generated_by: UUID | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    advisory_only: Literal[True] = True
    requires_review: Literal[True] = True
    is_clinical: Literal[False] = False
    disclaimer: Literal[
        "Observed-fact decision support only; no diagnosis, risk score, or validated clinical threshold."
    ] = "Observed-fact decision support only; no diagnosis, risk score, or validated clinical threshold."


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
