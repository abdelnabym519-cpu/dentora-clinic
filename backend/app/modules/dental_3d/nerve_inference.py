"""Infrastructure adapters for CBCT acquisition and nerve inference.

DICOM, media storage, SQLAlchemy and HTTP stay here. The adapter produces a
deterministic, bounded and de-identified DICOM archive for an
operator-configured model service. No model ships with Dentora, so an
unconfigured deployment returns an explicit missing-model outcome.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydicom import dcmread
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.errors import InvalidDicomError
from pydicom.uid import PYDICOM_IMPLEMENTATION_UID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.media.models import Document as MediaDocument
from app.modules.media.storage import StorageBackend, get_storage_backend

from .cbct import (
    DICOM_MEDIA_MIME,
    DICOM_METADATA_KEY,
    CbctSeriesDescriptor,
    DicomInstanceMetadata,
)
from .nerve import (
    NerveConfidenceSummary,
    NerveDetectionFailure,
    NerveDetectionFailureCode,
    NerveDetectionProvider,
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveEvidence,
    NerveModelProvenance,
    NervePathPoint,
    NervePathway,
    NerveReferenceSpace,
    NerveUncertainty,
)

ADAPTER_ID = "dentora-cbct-http-v1"
MAX_INFERENCE_RESPONSE_BYTES = 1024 * 1024

# Pixel data plus the minimum geometry/intensity description. Patient names,
# descriptions, operator fields and all private tags are deliberately absent.
_SAFE_DATASET_KEYWORDS = (
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "FrameOfReferenceUID",
    "Modality",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
    "ImagePositionPatient",
    "ImageOrientationPatient",
    "SamplesPerPixel",
    "PhotometricInterpretation",
    "PlanarConfiguration",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "RescaleIntercept",
    "RescaleSlope",
    "PixelData",
)


class _ServiceUncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: float = Field(ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=255)


class _ServicePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    z: float = Field(ge=-1_000_000, le=1_000_000)


class _ServiceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: str | None = Field(default=None, min_length=1, max_length=128)
    side: Literal["left", "right"]
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: _ServiceUncertainty | None = None
    points_mm: list[_ServicePoint] = Field(min_length=2, max_length=2048)


class _ServiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["detected", "no_detection", "uncertain"]
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    findings: list[_ServiceFinding] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _status_matches_findings(self) -> _ServiceResponse:
        if self.status == "no_detection" and self.findings:
            raise ValueError("no-detection response cannot contain findings")
        if self.status != "no_detection" and not self.findings:
            raise ValueError("detected/uncertain response requires findings")
        supplied_ids = [item.finding_id for item in self.findings if item.finding_id]
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ValueError("finding identifiers must be unique")
        return self


@dataclass(frozen=True)
class PreparedDicomSeries:
    archive: bytes
    digest: str
    descriptor: CbctSeriesDescriptor
    document_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class InferenceServiceResult:
    response: _ServiceResponse
    duration_ms: int


class NerveInferenceAdapterError(Exception):
    """Expected infrastructure failure carrying only safe public detail."""

    def __init__(self, code: NerveDetectionFailureCode, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(code.value)


class UnavailableNerveInferenceEngine:
    async def infer(self, prepared: PreparedDicomSeries) -> InferenceServiceResult:
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.MISSING_MODEL,
            "No nerve inference model service is configured",
        )


class HttpNerveInferenceEngine:
    """Bounded HTTP adapter for an operator-controlled inference service."""

    def __init__(
        self,
        *,
        url: str,
        token: str = "",
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def infer(self, prepared: PreparedDicomSeries) -> InferenceServiceResult:
        headers = {
            "Content-Type": "application/zip",
            "Accept": "application/json",
            "X-Dentora-Input-Digest": prepared.digest,
            "X-Dentora-Contract": "nerve-detection-v1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        started = monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(self._url, content=prepared.archive, headers=headers)
        except httpx.RequestError as exc:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INFERENCE_FAILED,
                "The nerve inference service could not be reached",
            ) from exc
        duration_ms = max(0, round((monotonic() - started) * 1000))
        if response.status_code >= 500:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INFERENCE_FAILED,
                "The nerve inference service failed",
            )
        if response.status_code >= 400:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.MODEL_INITIALIZATION_FAILED,
                "The nerve inference service rejected the configured model or input",
            )
        try:
            content_length = int(response.headers.get("content-length", "0"))
        except ValueError:
            content_length = MAX_INFERENCE_RESPONSE_BYTES + 1
        if (
            content_length > MAX_INFERENCE_RESPONSE_BYTES
            or len(response.content) > MAX_INFERENCE_RESPONSE_BYTES
        ):
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.MALFORMED_OUTPUT,
                "The nerve inference response exceeded the allowed size",
            )
        try:
            parsed = _ServiceResponse.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.MALFORMED_OUTPUT,
                "The nerve inference service returned malformed output",
            ) from exc
        return InferenceServiceResult(response=parsed, duration_ms=duration_ms)


def _slice_position(metadata: DicomInstanceMetadata) -> tuple[int, float, str]:
    """Deterministic geometric slice order with SOP UID fallback."""
    position = metadata.image_position_patient_mm
    orientation = metadata.image_orientation_patient
    if position is None or orientation is None:
        return (1, 0.0, metadata.sop_instance_uid)
    row, column = orientation[:3], orientation[3:]
    normal = (
        row[1] * column[2] - row[2] * column[1],
        row[2] * column[0] - row[0] * column[2],
        row[0] * column[1] - row[1] * column[0],
    )
    return (
        0,
        sum(position[index] * normal[index] for index in range(3)),
        metadata.sop_instance_uid,
    )


def _sanitized_dicom(data: bytes, expected: DicomInstanceMetadata | None = None) -> bytes:
    """Return a Part 10 instance containing only safe inference tags."""
    try:
        source = dcmread(BytesIO(data), force=False)
    except (InvalidDicomError, EOFError, OSError, ValueError) as exc:
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.INVALID_INPUT,
            "A stored DICOM instance could not be parsed",
        ) from exc
    if str(getattr(source, "Modality", "")).upper() != "CT":
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.UNSUPPORTED_MODALITY,
            "Only CT DICOM input is supported for nerve inference",
        )
    if expected is not None and any(
        str(getattr(source, keyword, "")) != value
        for keyword, value in (
            ("StudyInstanceUID", expected.study_instance_uid),
            ("SeriesInstanceUID", expected.series_instance_uid),
            ("SOPInstanceUID", expected.sop_instance_uid),
            ("FrameOfReferenceUID", expected.frame_of_reference_uid or ""),
        )
    ):
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.INVALID_GEOMETRY,
            "Stored DICOM content does not match its normalized geometry metadata",
        )
    if "PixelData" not in source:
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.INVALID_INPUT,
            "A stored DICOM instance has no pixel data",
        )
    transfer = getattr(source.file_meta, "TransferSyntaxUID", None)
    sop_class = getattr(source.file_meta, "MediaStorageSOPClassUID", None)
    sop_instance = getattr(source.file_meta, "MediaStorageSOPInstanceUID", None)
    if not transfer or not sop_class or not sop_instance:
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.INVALID_INPUT,
            "A stored DICOM instance has incomplete file metadata",
        )
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = transfer
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = sop_instance
    file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    sanitized = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    for keyword in _SAFE_DATASET_KEYWORDS:
        element = source.data_element(keyword) if keyword in source else None
        if element is not None:
            sanitized.add(copy.deepcopy(element))
    output = BytesIO()
    sanitized.save_as(output, enforce_file_format=True)
    return output.getvalue()


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_STORED
    info.external_attr = 0o600 << 16
    return info


class CbctNerveDetectionProvider:
    """Acquire one patient-owned CBCT series and run replaceable inference."""

    name = "cbct-model-service"
    input_kind = "cbct_series"

    def __init__(
        self,
        *,
        db: AsyncSession,
        engine: UnavailableNerveInferenceEngine | HttpNerveInferenceEngine,
        storage: StorageBackend,
        max_instances: int = 512,
        max_input_bytes: int = 256 * 1024 * 1024,
        low_confidence_threshold: float = 0.6,
    ) -> None:
        self._db = db
        self._engine = engine
        self._storage = storage
        self._max_instances = max_instances
        self._max_input_bytes = max_input_bytes
        self._low_confidence_threshold = low_confidence_threshold

    def _failure(
        self,
        request: NerveDetectionRequest,
        code: NerveDetectionFailureCode,
        message: str,
    ) -> NerveDetectionResult:
        return NerveDetectionResult(
            status="failed",
            provider=self.name,
            method=ADAPTER_ID,
            input_kind="cbct_series",
            requires_review=False,
            failure=NerveDetectionFailure(code=code, message=message),
            performed_at=request.performed_at,
        )

    def _select_series(self, request: NerveDetectionRequest) -> CbctSeriesDescriptor:
        if not request.cbct_series:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INVALID_INPUT,
                "No validated CBCT series is available for this patient",
            )
        selected = request.cbct_series[0]
        if request.requested_series_instance_uid:
            match = next(
                (
                    item
                    for item in request.cbct_series
                    if item.series_instance_uid == request.requested_series_instance_uid
                ),
                None,
            )
            if match is None:
                raise NerveInferenceAdapterError(
                    NerveDetectionFailureCode.INVALID_INPUT,
                    "The requested CBCT series is not available for this patient",
                )
            selected = match
        if selected.catalog_truncated:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INVALID_INPUT,
                "The CBCT series catalog is incomplete",
            )
        if selected.instance_count > self._max_instances:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INVALID_INPUT,
                "The CBCT series exceeds the inference instance limit",
            )
        if selected.frame_of_reference_uid is None:
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INVALID_GEOMETRY,
                "The CBCT series has no consistent DICOM frame of reference",
            )
        return selected

    async def _prepare(
        self, request: NerveDetectionRequest, descriptor: CbctSeriesDescriptor
    ) -> PreparedDicomSeries:
        stmt = select(MediaDocument).where(
            MediaDocument.id.in_(descriptor.document_ids),
            MediaDocument.clinic_id == request.clinic_id,
            MediaDocument.patient_id == request.patient_id,
            MediaDocument.status == "active",
            MediaDocument.mime_type == DICOM_MEDIA_MIME,
        )
        documents = list((await self._db.execute(stmt)).scalars().all())
        if len(documents) != len(descriptor.document_ids):
            raise NerveInferenceAdapterError(
                NerveDetectionFailureCode.INVALID_INPUT,
                "The selected CBCT series is incomplete",
            )
        instances: list[tuple[DicomInstanceMetadata, bytes]] = []
        total_bytes = 0
        for document in documents:
            envelope = (document.extra_data or {}).get(DICOM_METADATA_KEY)
            payload = envelope.get("metadata") if isinstance(envelope, dict) else None
            try:
                metadata = DicomInstanceMetadata.model_validate(payload)
            except ValidationError as exc:
                raise NerveInferenceAdapterError(
                    NerveDetectionFailureCode.INVALID_INPUT,
                    "A stored CBCT instance has invalid normalized metadata",
                ) from exc
            if (
                metadata.study_instance_uid != descriptor.study_instance_uid
                or metadata.series_instance_uid != descriptor.series_instance_uid
                or metadata.frame_of_reference_uid != descriptor.frame_of_reference_uid
            ):
                raise NerveInferenceAdapterError(
                    NerveDetectionFailureCode.INVALID_GEOMETRY,
                    "CBCT instance geometry does not match the selected series",
                )
            raw = await self._storage.retrieve(document.storage_path)
            total_bytes += len(raw)
            if total_bytes > self._max_input_bytes:
                raise NerveInferenceAdapterError(
                    NerveDetectionFailureCode.INVALID_INPUT,
                    "The CBCT series exceeds the inference byte limit",
                )
            instances.append((metadata, _sanitized_dicom(raw, metadata)))
        instances.sort(key=lambda item: _slice_position(item[0]))
        manifest = {
            "contract": "dentora-nerve-input-v1",
            "study_instance_uid": descriptor.study_instance_uid,
            "series_instance_uid": descriptor.series_instance_uid,
            "frame_of_reference_uid": descriptor.frame_of_reference_uid,
            "instance_count": len(instances),
            "instances": [
                {
                    "file": f"{index:04d}.dcm",
                    "sop_instance_uid": metadata.sop_instance_uid,
                    "position_mm": metadata.image_position_patient_mm,
                    "orientation": metadata.image_orientation_patient,
                }
                for index, (metadata, _) in enumerate(instances)
            ],
        }
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(
                _zip_info("manifest.json"),
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
            )
            for index, (_, data) in enumerate(instances):
                archive.writestr(_zip_info(f"{index:04d}.dcm"), data)
        payload = buffer.getvalue()
        return PreparedDicomSeries(
            archive=payload,
            digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            descriptor=descriptor,
            document_ids=tuple(descriptor.document_ids),
        )

    @staticmethod
    def _finding_id(
        finding: _ServiceFinding,
        response: _ServiceResponse,
        series_uid: str,
    ) -> str:
        if finding.finding_id:
            return finding.finding_id
        canonical = json.dumps(
            {
                "model": [response.model_id, response.model_version],
                "series": series_uid,
                "side": finding.side,
                "points": [point.model_dump() for point in finding.points_mm],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        try:
            descriptor = self._select_series(request)
            prepared = await self._prepare(request, descriptor)
            service_result = await self._engine.infer(prepared)
            response = service_result.response
            provenance = NerveModelProvenance(
                model_id=response.model_id,
                model_version=response.model_version,
                adapter=ADAPTER_ID,
                input_digest=prepared.digest,
                study_instance_uid=descriptor.study_instance_uid,
                series_instance_uid=descriptor.series_instance_uid,
                frame_of_reference_uid=descriptor.frame_of_reference_uid,
            )
            if response.status == "no_detection":
                return NerveDetectionResult(
                    status="no_detection",
                    provider=self.name,
                    method=ADAPTER_ID,
                    input_kind="cbct_series",
                    requires_review=True,
                    provenance=provenance,
                    inference_duration_ms=service_result.duration_ms,
                    performed_at=request.performed_at,
                )
            pathways: list[NervePathway] = []
            for finding in response.findings:
                uncertain = (
                    response.status == "uncertain"
                    or finding.confidence < self._low_confidence_threshold
                )
                pathways.append(
                    NervePathway(
                        finding_id=self._finding_id(
                            finding, response, descriptor.series_instance_uid
                        ),
                        side=finding.side,
                        source="model_inference",
                        status="uncertain" if uncertain else "detected",
                        confidence=finding.confidence,
                        uncertainty=(
                            NerveUncertainty(
                                kind="model_reported",
                                value=finding.uncertainty.value,
                                note=finding.uncertainty.note,
                            )
                            if finding.uncertainty
                            else NerveUncertainty(kind="not_reported")
                        ),
                        reference_space=NerveReferenceSpace(
                            kind="dicom_patient",
                            unit="mm",
                            frame_of_reference_uid=descriptor.frame_of_reference_uid,
                        ),
                        points=[
                            NervePathPoint(x=point.x, y=point.y, z=point.z)
                            for point in finding.points_mm
                        ],
                        evidence=NerveEvidence(
                            basis="cbct_inference",
                            note="model inference on de-identified CBCT pixel data",
                            backing_documents=list(descriptor.document_ids),
                        ),
                    )
                )
            confidence = [pathway.confidence for pathway in pathways]
            return NerveDetectionResult(
                status=(
                    "uncertain"
                    if any(pathway.status == "uncertain" for pathway in pathways)
                    else "detected"
                ),
                provider=self.name,
                method=ADAPTER_ID,
                input_kind="cbct_series",
                requires_review=True,
                pathways=pathways,
                provenance=provenance,
                confidence_summary=NerveConfidenceSummary(
                    count=len(confidence),
                    minimum=min(confidence),
                    maximum=max(confidence),
                    mean=sum(confidence) / len(confidence),
                ),
                inference_duration_ms=service_result.duration_ms,
                performed_at=request.performed_at,
            )
        except NerveInferenceAdapterError as exc:
            return self._failure(request, exc.code, exc.safe_message)
        except (FileNotFoundError, OSError):
            return self._failure(
                request,
                NerveDetectionFailureCode.INVALID_INPUT,
                "A stored CBCT instance is unavailable",
            )
        except ValidationError:
            return self._failure(
                request,
                NerveDetectionFailureCode.INVALID_GEOMETRY,
                "The inference output contained invalid nerve geometry",
            )
        except Exception:
            return self._failure(
                request,
                NerveDetectionFailureCode.INFERENCE_FAILED,
                "Nerve inference failed unexpectedly",
            )


class _InvalidConfigurationEngine(UnavailableNerveInferenceEngine):
    async def infer(self, prepared: PreparedDicomSeries) -> InferenceServiceResult:
        raise NerveInferenceAdapterError(
            NerveDetectionFailureCode.MODEL_INITIALIZATION_FAILED,
            "The nerve inference service configuration is invalid",
        )


def _configured_engine() -> UnavailableNerveInferenceEngine | HttpNerveInferenceEngine:
    url = settings.DENTAL_3D_NERVE_INFERENCE_URL.strip()
    if not url:
        return UnavailableNerveInferenceEngine()
    parsed = urlsplit(url)
    invalid = (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    )
    if invalid or (settings.ENVIRONMENT == "production" and parsed.scheme != "https"):
        return _InvalidConfigurationEngine()
    return HttpNerveInferenceEngine(
        url=url,
        token=settings.DENTAL_3D_NERVE_INFERENCE_TOKEN,
        timeout_seconds=settings.DENTAL_3D_NERVE_INFERENCE_TIMEOUT_SECONDS,
    )


def default_cbct_nerve_provider(db: AsyncSession) -> NerveDetectionProvider:
    """Composition root for the Phase 5.2 production adapter."""
    return CbctNerveDetectionProvider(
        db=db,
        engine=_configured_engine(),
        storage=get_storage_backend(),
        max_instances=settings.DENTAL_3D_NERVE_MAX_INSTANCES,
        max_input_bytes=settings.DENTAL_3D_NERVE_MAX_INPUT_BYTES,
        low_confidence_threshold=settings.DENTAL_3D_NERVE_LOW_CONFIDENCE_THRESHOLD,
    )
