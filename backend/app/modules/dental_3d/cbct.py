"""CBCT/DICOM ingestion contracts — framework-independent inner boundary.

Phase 5.1 makes validated DICOM data *available* to Dental 3D. It does not
decode pixels, infer anatomy, detect pathology or nerves, plan implants, or
make a clinical decision. DICOM parsing and media persistence are external
capabilities implemented behind :class:`DicomIngestionPort` in
``infrastructure.py`` (ADR 0019 / ADR 0023).

Only normalized, non-diagnostic metadata crosses this boundary. Patient
identity is deliberately absent: the authenticated clinic/patient route is
authoritative, while identifying tags remain protected inside the original
media document and are never copied into scene responses.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DicomModality = Literal["CT"]
DicomSource = Literal["dicom"]
CbctAvailabilityStatus = Literal["available"]

# Canonical media vocabulary shared by the ingestion and inference adapters.
DICOM_MEDIA_MIME = "application/dicom"
DICOM_METADATA_KEY = "dental_3d_cbct"


class DicomIngestionErrorCode(StrEnum):
    """Stable failure vocabulary shared by application and presentation."""

    EMPTY_FILE = "empty_file"
    TOO_LARGE = "too_large"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    MIME_MISMATCH = "mime_mismatch"
    MALFORMED_DICOM = "malformed_dicom"
    UNSUPPORTED_MODALITY = "unsupported_modality"
    MISSING_METADATA = "missing_metadata"
    UNSUPPORTED_DICOMDIR = "unsupported_dicomdir"
    INVALID_REQUEST = "invalid_request"


class DicomIngestionError(ValueError):
    """Expected ingestion failure safe to map to a client error."""

    def __init__(self, code: DicomIngestionErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


def _validate_uid(value: str) -> str:
    """Validate a DICOM UID without importing a DICOM implementation."""
    if len(value) > 64 or not value or value.startswith(".") or value.endswith("."):
        raise ValueError("invalid DICOM UID")
    parts = value.split(".")
    if any(not part.isdigit() or (len(part) > 1 and part.startswith("0")) for part in parts):
        raise ValueError("invalid DICOM UID")
    return value


class DicomInstanceMetadata(BaseModel):
    """Normalized non-identifying metadata for one DICOM CT instance."""

    model_config = ConfigDict(allow_inf_nan=False)

    source: DicomSource = "dicom"
    modality: DicomModality
    sop_class_uid: str = Field(max_length=64)
    study_instance_uid: str = Field(max_length=64)
    series_instance_uid: str = Field(max_length=64)
    sop_instance_uid: str = Field(max_length=64)
    transfer_syntax_uid: str = Field(max_length=64)
    frame_of_reference_uid: str | None = Field(default=None, max_length=64)
    rows: int = Field(ge=1, le=65535)
    columns: int = Field(ge=1, le=65535)
    number_of_frames: int = Field(default=1, ge=1, le=1_000_000)
    pixel_spacing_mm: tuple[float, float] | None = None
    slice_thickness_mm: float | None = Field(default=None, gt=0)
    image_position_patient_mm: tuple[float, float, float] | None = None
    image_orientation_patient: tuple[float, float, float, float, float, float] | None = None
    manufacturer: str | None = Field(default=None, max_length=100)
    manufacturer_model: str | None = Field(default=None, max_length=100)

    @field_validator(
        "sop_class_uid",
        "study_instance_uid",
        "series_instance_uid",
        "sop_instance_uid",
        "transfer_syntax_uid",
        "frame_of_reference_uid",
    )
    @classmethod
    def _uids_are_valid(cls, value: str | None) -> str | None:
        return None if value is None else _validate_uid(value)

    @field_validator("pixel_spacing_mm")
    @classmethod
    def _spacing_is_positive(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and any(component <= 0 for component in value):
            raise ValueError("pixel spacing values must be positive")
        return value


class CbctSeriesDescriptor(BaseModel):
    """Normalized availability descriptor for one patient CBCT series.

    This is a catalog entry, not renderable geometry and not a clinical
    interpretation. ``document_ids`` point to media-owned DICOM instances;
    authorized content access remains on media's download route.
    """

    model_config = ConfigDict(allow_inf_nan=False)

    source: Literal["cbct"] = "cbct"
    modality: DicomModality = "CT"
    status: CbctAvailabilityStatus = "available"
    study_instance_uid: str = Field(max_length=64)
    series_instance_uid: str = Field(max_length=64)
    frame_of_reference_uid: str | None = Field(default=None, max_length=64)
    document_ids: list[UUID] = Field(min_length=1, max_length=2048)
    instance_count: int = Field(ge=1, le=2048)
    frame_count: int = Field(ge=1)
    rows: int | None = Field(default=None, ge=1, le=65535)
    columns: int | None = Field(default=None, ge=1, le=65535)
    pixel_spacing_mm: tuple[float, float] | None = None
    slice_thickness_mm: float | None = Field(default=None, gt=0)
    manufacturer: str | None = Field(default=None, max_length=100)
    manufacturer_model: str | None = Field(default=None, max_length=100)
    latest_uploaded_at: datetime
    catalog_truncated: bool = False
    non_diagnostic: Literal[True] = True

    @field_validator("study_instance_uid", "series_instance_uid", "frame_of_reference_uid")
    @classmethod
    def _uids_are_valid(cls, value: str | None) -> str | None:
        return None if value is None else _validate_uid(value)

    @field_validator("pixel_spacing_mm")
    @classmethod
    def _spacing_is_positive(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and any(component <= 0 for component in value):
            raise ValueError("pixel spacing values must be positive")
        return value


class DicomIngestionRequest(BaseModel):
    """Validated application input for one uploaded DICOM Part 10 file."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=100)
    data: bytes
    title: str | None = Field(default=None, max_length=255)


class DicomIngestionReceipt(BaseModel):
    """Successful ingestion result; raw pixel data is never returned."""

    document_id: UUID
    download_url: str = Field(max_length=500)
    metadata: DicomInstanceMetadata
    non_diagnostic: Literal[True] = True


@runtime_checkable
class DicomIngestionPort(Protocol):
    """Port for validation/normalization plus storage of one DICOM instance."""

    name: str

    async def ingest(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        request: DicomIngestionRequest,
    ) -> DicomIngestionReceipt:
        """Validate and persist one instance inside the existing media system."""
        ...
