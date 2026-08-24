"""Framework-independent contracts for mandibular nerve detection.

ADR 0019 / ADR 0022 define :class:`NerveDetectionProvider` as the
replaceable inner-boundary port. Phase 5.2 evolves that seam from canonical
demonstration geometry to truthful CBCT inference outcomes without coupling
domain/application code to pydicom, storage, HTTP, a model runtime or
visualization.

The contracts distinguish a finding, explicit no-detection, uncertainty and
operational failure. Every non-failed inference remains non-clinical decision
support and requires dentist review. Native CBCT geometry stays in DICOM
patient coordinates; no multimodal alignment or planning occurs here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cbct import CbctSeriesDescriptor, _validate_uid
from .schemas import DentalMesh, Tooth3D, _is_valid_fdi

NerveDetectionInputKind = Literal["scene", "cbct_series"]
NerveDetectionOutcome = Literal["detected", "no_detection", "uncertain", "failed"]
NerveRegion = Literal["mandibular_canal"]
NerveSide = Literal["left", "right"]
NervePathwayStatus = Literal["detected", "uncertain"]
NervePathwaySource = Literal["canonical_demo_model", "model_inference"]
NerveReferenceSpaceKind = Literal["canonical_arch", "dicom_patient"]
NerveProximityWarning = Literal["near", "watch", "none"]
NerveReviewDecision = Literal["accepted", "rejected"]
NerveReviewStatus = Literal["pending", "accepted", "rejected", "not_applicable"]

CONFIDENCE_HIGH = 0.8
CONFIDENCE_MEDIUM = 0.6
PROXIMITY_NEAR_MM = 2.0
PROXIMITY_WATCH_MM = 5.0
PROXIMITY_MAX_MM = 15.0


class NerveDetectionFailureCode(StrEnum):
    """Stable, safe failure vocabulary for application/API consumers."""

    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_MODALITY = "unsupported_modality"
    MISSING_MODEL = "missing_model"
    MODEL_INITIALIZATION_FAILED = "model_initialization_failed"
    INFERENCE_FAILED = "inference_failed"
    MALFORMED_OUTPUT = "malformed_output"
    INVALID_GEOMETRY = "invalid_geometry"


class NerveDetectionFailure(BaseModel):
    """Sanitized failure detail; never contains paths, URLs or stack traces."""

    code: NerveDetectionFailureCode
    message: str = Field(min_length=1, max_length=255)


class NerveReferenceSpace(BaseModel):
    """Coordinate system in which pathway points are expressed."""

    kind: NerveReferenceSpaceKind
    unit: Literal["model_unit", "mm"]
    frame_of_reference_uid: str | None = Field(default=None, max_length=64)

    @field_validator("frame_of_reference_uid")
    @classmethod
    def _valid_frame_uid(cls, value: str | None) -> str | None:
        return None if value is None else _validate_uid(value)

    @model_validator(mode="after")
    def _space_is_consistent(self) -> NerveReferenceSpace:
        if self.kind == "dicom_patient":
            if self.unit != "mm" or self.frame_of_reference_uid is None:
                raise ValueError("DICOM patient coordinates require mm and a frame UID")
        elif self.unit != "model_unit" or self.frame_of_reference_uid is not None:
            raise ValueError("canonical coordinates require model units and no frame UID")
        return self


class NerveUncertainty(BaseModel):
    """Model-reported uncertainty when the inference service supplies it."""

    kind: Literal["model_reported", "not_reported"]
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _value_matches_kind(self) -> NerveUncertainty:
        if self.kind == "model_reported" and self.value is None:
            raise ValueError("model-reported uncertainty requires a value")
        if self.kind == "not_reported" and self.value is not None:
            raise ValueError("unreported uncertainty cannot invent a value")
        return self


class NerveModelProvenance(BaseModel):
    """Traceability for a model-backed inference operation."""

    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    adapter: str = Field(min_length=1, max_length=100)
    input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    study_instance_uid: str = Field(max_length=64)
    series_instance_uid: str = Field(max_length=64)
    frame_of_reference_uid: str = Field(max_length=64)

    @field_validator("study_instance_uid", "series_instance_uid", "frame_of_reference_uid")
    @classmethod
    def _valid_uids(cls, value: str) -> str:
        return _validate_uid(value)


class NerveEvidence(BaseModel):
    """What informed a pathway; explanatory, never proof of correctness."""

    basis: Literal["anatomical_model", "mesh_backed", "cbct_inference"]
    note: str | None = Field(default=None, max_length=255)
    backing_documents: list[UUID] = Field(default_factory=list, max_length=512)


class NervePathPoint(BaseModel):
    """One finite 3D point in the pathway's declared reference space."""

    model_config = ConfigDict(allow_inf_nan=False)

    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    z: float = Field(ge=-1_000_000, le=1_000_000)


class NervePathway(BaseModel):
    """One structured mandibular-canal finding."""

    finding_id: str | None = Field(default=None, min_length=1, max_length=128)
    side: NerveSide
    region: NerveRegion = "mandibular_canal"
    source: NervePathwaySource
    status: NervePathwayStatus
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: NerveUncertainty | None = None
    reference_space: NerveReferenceSpace = Field(
        default_factory=lambda: NerveReferenceSpace(kind="canonical_arch", unit="model_unit")
    )
    points: list[NervePathPoint] = Field(min_length=2, max_length=2048)
    evidence: NerveEvidence

    @model_validator(mode="after")
    def _geometry_and_provenance_are_valid(self) -> NervePathway:
        if len({(point.x, point.y, point.z) for point in self.points}) < 2:
            raise ValueError("a nerve pathway requires at least two distinct points")
        if self.source == "model_inference":
            if self.finding_id is None:
                raise ValueError("model inference findings require a stable identifier")
            if self.reference_space.kind != "dicom_patient":
                raise ValueError("model inference findings require DICOM patient coordinates")
            if self.evidence.basis != "cbct_inference":
                raise ValueError("model inference findings require CBCT inference evidence")
        return self


class ToothNerveProximity(BaseModel):
    """Legacy Phase 4 model-space proximity; never a safety verdict."""

    tooth_number: int
    side: NerveSide
    distance_mm: float = Field(ge=0.0, le=100.0)
    closest_point_index: int = Field(ge=0)
    warning: NerveProximityWarning
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("tooth_number")
    @classmethod
    def _valid_fdi(cls, value: int) -> int:
        if not _is_valid_fdi(value):
            raise ValueError(f"{value} is not a valid FDI tooth number")
        return value


class NerveConfidenceSummary(BaseModel):
    """Observed confidence values; no unreported measurement is invented."""

    count: int = Field(ge=1, le=4)
    minimum: float = Field(ge=0.0, le=1.0)
    maximum: float = Field(ge=0.0, le=1.0)
    mean: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> NerveConfidenceSummary:
        if self.minimum > self.mean or self.mean > self.maximum:
            raise ValueError("confidence summary must be ordered")
        return self


class NerveDetectionRunRequest(BaseModel):
    """Optional presentation input selecting one patient-owned CBCT series."""

    series_instance_uid: str | None = Field(default=None, max_length=64)

    @field_validator("series_instance_uid")
    @classmethod
    def _valid_series_uid(cls, value: str | None) -> str | None:
        return None if value is None else _validate_uid(value)


class NerveDetectionRequest(BaseModel):
    """Clinic-scoped application input assembled server-side."""

    clinic_id: UUID
    patient_id: UUID
    teeth: list[Tooth3D] = Field(default_factory=list, max_length=52)
    meshes: list[DentalMesh] = Field(default_factory=list, max_length=16)
    cbct_series: list[CbctSeriesDescriptor] = Field(default_factory=list, max_length=32)
    requested_series_instance_uid: str | None = Field(default=None, max_length=64)
    performed_at: datetime

    @field_validator("requested_series_instance_uid")
    @classmethod
    def _valid_requested_uid(cls, value: str | None) -> str | None:
        return None if value is None else _validate_uid(value)


class NerveDetectionResult(BaseModel):
    """Provider output with explicit clinical and operational semantics."""

    status: NerveDetectionOutcome
    provider: str = Field(min_length=1, max_length=50)
    method: str = Field(min_length=1, max_length=100)
    input_kind: NerveDetectionInputKind
    is_clinical: Literal[False] = False
    requires_review: bool
    pathways: list[NervePathway] = Field(default_factory=list, max_length=4)
    proximities: list[ToothNerveProximity] = Field(default_factory=list, max_length=52)
    failure: NerveDetectionFailure | None = None
    provenance: NerveModelProvenance | None = None
    confidence_summary: NerveConfidenceSummary | None = None
    inference_duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    performed_at: datetime

    @model_validator(mode="after")
    def _outcome_is_consistent(self) -> NerveDetectionResult:
        if self.status == "failed":
            if self.failure is None or self.pathways or self.proximities or self.requires_review:
                raise ValueError("failed detection requires only a failure and no review")
            return self
        if self.failure is not None or not self.requires_review:
            raise ValueError("non-failed inference requires review and no failure")
        if self.input_kind == "cbct_series" and self.provenance is None:
            raise ValueError("CBCT inference outcomes require model provenance")
        if self.status == "no_detection":
            if self.pathways or self.confidence_summary is not None:
                raise ValueError("no-detection cannot contain findings or confidence")
            return self
        if not self.pathways or self.confidence_summary is None:
            raise ValueError("detected/uncertain outcomes require findings and confidence")
        if self.status == "detected" and any(
            pathway.status != "detected" for pathway in self.pathways
        ):
            raise ValueError("detected outcome cannot contain uncertain pathways")
        if self.status == "uncertain" and all(
            pathway.status == "detected" for pathway in self.pathways
        ):
            raise ValueError("uncertain outcome requires an uncertain pathway")
        if any(pathway.source == "model_inference" for pathway in self.pathways):
            if self.input_kind != "cbct_series" or self.provenance is None:
                raise ValueError("CBCT model findings require CBCT provenance")
            if self.proximities:
                raise ValueError("tooth proximity requires out-of-scope patient alignment")
        return self

    @property
    def detected(self) -> list[NervePathway]:
        return [pathway for pathway in self.pathways if pathway.status == "detected"]

    @property
    def uncertain(self) -> list[NervePathway]:
        return [pathway for pathway in self.pathways if pathway.status == "uncertain"]

    @property
    def near_teeth(self) -> list[ToothNerveProximity]:
        return [item for item in self.proximities if item.warning == "near"]


@runtime_checkable
class NerveDetectionProvider(Protocol):
    """Replaceable inference boundary used by the application service."""

    name: str
    input_kind: NerveDetectionInputKind

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        """Return a structured outcome; never leak infrastructure exceptions."""
        ...


class NerveDetectionAnalysisResponse(BaseModel):
    """Persisted analysis plus dentist-review and traceability state."""

    id: UUID
    patient_id: UUID
    status: NerveDetectionOutcome
    provider: str
    method: str
    input_kind: NerveDetectionInputKind
    is_clinical: Literal[False] = False
    requires_review: bool
    pathways: list[NervePathway] = Field(default_factory=list, max_length=4)
    proximities: list[ToothNerveProximity] = Field(default_factory=list, max_length=52)
    failure: NerveDetectionFailure | None = None
    provenance: NerveModelProvenance | None = None
    confidence_summary: NerveConfidenceSummary | None = None
    inference_duration_ms: int | None = None
    performed_at: datetime
    created_at: datetime | None = None
    review_status: NerveReviewStatus
    reviewed_at: datetime | None = None
    review_note: str | None = None
    pathway_count: int = Field(default=0, ge=0)
    uncertain_count: int = Field(default=0, ge=0)
    near_count: int = Field(default=0, ge=0)
    watch_count: int = Field(default=0, ge=0)
    disclaimer: str = (
        "Model-generated nerve output is non-clinical decision support. "
        "Detected, uncertain and no-detection outcomes require dentist verification; "
        "a failed operation contains no anatomical finding."
    )

    def counts_from_result(self) -> None:
        self.pathway_count = len(self.pathways)
        self.uncertain_count = sum(1 for pathway in self.pathways if pathway.status == "uncertain")
        self.near_count = sum(1 for item in self.proximities if item.warning == "near")
        self.watch_count = sum(1 for item in self.proximities if item.warning == "watch")


class NerveReviewUpdate(BaseModel):
    """Dentist acknowledgement of a non-failed inference result."""

    decision: NerveReviewDecision
    note: str | None = Field(default=None, max_length=1000)
