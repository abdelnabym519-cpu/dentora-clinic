"""Patient-specific rigid registration contracts and ports.

The domain owns coordinate-frame, SE(3), provenance, metrics, failure and
review semantics.  Media, DICOM, DentalSegmentator, Open3D and TEASER++ stay
behind the protocols at the infrastructure edge.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AlignmentStatus = Literal["pending_review", "accepted", "rejected", "failed", "uncertain"]
LengthUnit = Literal["mm", "cm", "m", "inch"]
MeshContainer = Literal["stl", "ply", "obj"]

CLINICAL_THRESHOLD_NOT_VALIDATED = "CLINICAL_THRESHOLD_NOT_VALIDATED"


class AlignmentFailureCode(StrEnum):
    MISSING_CBCT = "missing_cbct"
    MISSING_IOS = "missing_ios"
    MISSING_FRAME_OF_REFERENCE = "missing_frame_of_reference"
    AMBIGUOUS_UNITS = "ambiguous_units"
    INVALID_GEOMETRY = "invalid_geometry"
    MALFORMED_MESH = "malformed_mesh"
    ANATOMY_EXTRACTION_FAILED = "anatomy_extraction_failed"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    REGISTRATION_FAILED = "registration_failed"


class Point3D(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    z: float = Field(ge=-1_000_000, le=1_000_000)


class CoordinateFrame(BaseModel):
    """Explicit frame metadata; no geometry is frame-free."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    kind: Literal["ios_mesh", "dicom_patient"]
    unit: Literal["mm"] = "mm"
    frame_of_reference_uid: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _dicom_frame_has_uid(self) -> CoordinateFrame:
        if self.kind == "dicom_patient" and not self.frame_of_reference_uid:
            raise ValueError("DICOM patient frame requires Frame of Reference UID")
        if self.kind == "ios_mesh" and self.frame_of_reference_uid is not None:
            raise ValueError("IOS mesh frame cannot claim a DICOM Frame of Reference UID")
        return self


class RigidTransform(BaseModel):
    """Homogeneous IOS→CBCT transform constrained to SE(3)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    matrix: list[list[float]]

    @field_validator("matrix")
    @classmethod
    def _valid_se3(cls, matrix: list[list[float]]) -> list[list[float]]:
        if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
            raise ValueError("rigid transform must be a 4x4 matrix")
        if any(not math.isfinite(value) for row in matrix for value in row):
            raise ValueError("rigid transform values must be finite")
        if any(
            abs(matrix[3][index] - expected) > 1e-7 for index, expected in enumerate((0, 0, 0, 1))
        ):
            raise ValueError("rigid transform must have homogeneous bottom row [0,0,0,1]")

        rotation = [row[:3] for row in matrix[:3]]
        for row in rotation:
            if abs(sum(value * value for value in row) - 1.0) > 1e-5:
                raise ValueError("rotation rows must have unit length")
        for left in range(3):
            for right in range(left + 1, 3):
                if abs(sum(rotation[left][i] * rotation[right][i] for i in range(3))) > 1e-5:
                    raise ValueError("rotation rows must be orthogonal")
        determinant = (
            rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
            - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
            + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
        )
        if abs(determinant - 1.0) > 1e-5:
            raise ValueError("rotation determinant must be +1")
        return matrix


class GeometryProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=255)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    document_ids: list[UUID] = Field(default_factory=list, max_length=2048)
    original_unit: LengthUnit | None = None
    normalized_unit: Literal["mm"] = "mm"


class RegistrationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ios: GeometryProvenance
    cbct: GeometryProvenance
    anatomy_model_id: str = Field(min_length=1, max_length=100)
    anatomy_model_version: str = Field(min_length=1, max_length=100)


class RegistrationMetrics(BaseModel):
    """Deterministic technical metrics; none is a clinical threshold."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    initializer: Literal["teaser++", "open3d_ransac"]
    source_point_count: int = Field(ge=3)
    target_point_count: int = Field(ge=3)
    feature_correspondence_count: int = Field(ge=0)
    inlier_correspondence_count: int = Field(ge=0)
    global_fitness: float = Field(ge=0, le=1)
    global_inlier_rmse_mm: float = Field(ge=0)
    icp_fitness: float = Field(ge=0, le=1)
    icp_inlier_rmse_mm: float = Field(ge=0)
    overlap_ratio: float = Field(ge=0, le=1)
    icp_iterations: int = Field(ge=0)
    icp_converged: bool
    outlier_ratio: float = Field(ge=0, le=1)
    clinical_threshold_status: Literal["CLINICAL_THRESHOLD_NOT_VALIDATED"] = (
        CLINICAL_THRESHOLD_NOT_VALIDATED
    )


class AlignmentFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: AlignmentFailureCode
    message: str = Field(min_length=1, max_length=255)


class AlignmentResult(BaseModel):
    """Persisted and API-safe patient alignment result."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    patient_id: UUID
    status: AlignmentStatus
    transform: RigidTransform | None = None
    source_frame: CoordinateFrame | None = None
    target_frame: CoordinateFrame | None = None
    algorithm: str = Field(min_length=1, max_length=100)
    algorithm_version: str = Field(min_length=1, max_length=255)
    provenance: RegistrationProvenance | None = None
    metrics: RegistrationMetrics | None = None
    failure: AlignmentFailure | None = None
    performed_at: datetime
    created_at: datetime | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=1000)
    requires_review: bool = True
    is_clinical: Literal[False] = False
    disclaimer: Literal[
        "Technical registration only; clinical accuracy threshold is not validated. Dentist review required."
    ] = "Technical registration only; clinical accuracy threshold is not validated. Dentist review required."

    @model_validator(mode="after")
    def _outcome_is_coherent(self) -> AlignmentResult:
        if self.status == "failed":
            if self.failure is None or self.transform is not None:
                raise ValueError("failed alignment requires failure and forbids transform")
            if self.requires_review:
                raise ValueError("failed alignment is not reviewable")
        else:
            if any(
                item is None
                for item in (
                    self.transform,
                    self.source_frame,
                    self.target_frame,
                    self.provenance,
                    self.metrics,
                )
            ):
                raise ValueError(
                    "non-failed alignment requires transform, frames, provenance and metrics"
                )
            if self.failure is not None:
                raise ValueError("non-failed alignment cannot contain failure")
        return self


class AlignmentRunRequest(BaseModel):
    """Explicit identifiers and IOS units supplied by the caller."""

    model_config = ConfigDict(extra="forbid")

    mesh_document_id: UUID
    series_instance_uid: str = Field(min_length=1, max_length=64)
    ios_units: LengthUnit


class AlignmentReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class PreparedCbctAnatomyInput(BaseModel):
    """De-identified archive passed to a patient-anatomy adapter."""

    model_config = ConfigDict(extra="forbid")

    archive: bytes
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    series_instance_uid: str
    frame_of_reference_uid: str
    document_ids: list[UUID] = Field(min_length=1, max_length=2048)


class ExtractedDentalAnatomy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points_mm: list[Point3D] = Field(min_length=3, max_length=500_000)
    frame_of_reference_uid: str
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)


class PreparedRegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID
    mesh_document_id: UUID
    mesh_format: MeshContainer
    mesh_bytes: bytes
    ios_units: LengthUnit
    ios_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cbct: PreparedCbctAnatomyInput


class RegistrationGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID
    mesh_document_id: UUID
    mesh_format: MeshContainer
    mesh_bytes: bytes
    ios_units: LengthUnit
    ios_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cbct: PreparedCbctAnatomyInput
    anatomy: ExtractedDentalAnatomy

    @model_validator(mode="after")
    def _same_patient_frame(self) -> RegistrationGeometry:
        if self.anatomy.frame_of_reference_uid != self.cbct.frame_of_reference_uid:
            raise ValueError("extracted anatomy does not match the CBCT frame")
        return self


@runtime_checkable
class RegistrationInputPort(Protocol):
    async def prepare(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        request: AlignmentRunRequest,
    ) -> PreparedRegistrationInput: ...


@runtime_checkable
class DentalAnatomyPort(Protocol):
    async def extract(self, prepared: PreparedCbctAnatomyInput) -> ExtractedDentalAnatomy: ...


@runtime_checkable
class RegistrationPort(Protocol):
    name: str

    def register(
        self, geometry: RegistrationGeometry, performed_at: datetime
    ) -> AlignmentResult: ...


__all__ = [
    "CLINICAL_THRESHOLD_NOT_VALIDATED",
    "AlignmentFailure",
    "AlignmentFailureCode",
    "AlignmentResult",
    "AlignmentReviewUpdate",
    "AlignmentRunRequest",
    "CoordinateFrame",
    "DentalAnatomyPort",
    "ExtractedDentalAnatomy",
    "GeometryProvenance",
    "Point3D",
    "PreparedCbctAnatomyInput",
    "PreparedRegistrationInput",
    "RegistrationGeometry",
    "RegistrationInputPort",
    "RegistrationMetrics",
    "RegistrationPort",
    "RegistrationProvenance",
    "RigidTransform",
]
