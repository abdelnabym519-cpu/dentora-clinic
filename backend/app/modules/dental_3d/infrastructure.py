"""Dental geometry source adapters — the infrastructure side of the port.

ADR 0020: everything that touches another module's database rows or
the outside world lives here, behind the ``DentalGeometrySource`` port
(``sources.py``). The application service depends on the port only;
this module is its composition root (``default_sources``).

Adapters:

- ``SyntheticGeometrySource`` — Phase 1 behaviour, unchanged: reads
  odontogram ``ToothRecord`` rows and synthesises the full default
  dentition. Regression-safe fallback for every future phase.
- ``IntraoralScanGeometrySource`` — Phase 2: discovers mesh documents
  (``model/stl`` / ``model/obj``) the patient already owns in the
  **media** module and describes them as scene meshes. No binary ever
  enters the scene payload — meshes are references to media documents,
  downloaded through media's own authorized route.
- ``PydicomMediaCbctAdapter`` / ``CbctDicomGeometrySource`` — Phase 5.1:
  validate DICOM Part 10 CT headers behind ``DicomIngestionPort``, store raw
  instances in media, and expose normalized series availability. No Pixel
  Data decoding, rendering or clinical inference.
- ``ArchPartitionSegmentationProvider`` — Phase 3: the deterministic,
  rule-based tooth-segmentation engine behind the
  ``ToothSegmentationProvider`` port (``segmentation.py``). Explicitly
  **not** a medical AI model; replaceable by a real ML adapter in the
  composition root (``default_segmentation_provider``) without
  touching any inner contract.
- ``default_nerve_provider`` — Phase 5.2 composition root for the bounded,
  de-identified CBCT inference adapter in ``nerve_inference.py``. An
  unconfigured service yields ``missing_model``; production never falls
  back to canonical anatomy.
"""

from __future__ import annotations

from io import BytesIO
from typing import TypeVar
from uuid import UUID

from pydantic import ValidationError
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.media.models import Document as MediaDocument
from app.modules.odontogram.constants import DECIDUOUS_TEETH, PERMANENT_TEETH, ToothCondition
from app.modules.odontogram.models import ToothRecord

from .cbct import (
    DICOM_MEDIA_MIME,
    DICOM_METADATA_KEY,
    CbctSeriesDescriptor,
    DicomIngestionError,
    DicomIngestionErrorCode,
    DicomIngestionPort,
    DicomIngestionReceipt,
    DicomIngestionRequest,
    DicomInstanceMetadata,
)
from .meshfiles import format_for_mime, mesh_download_url, mesh_mimes
from .nerve import (
    NerveDetectionProvider,
)
from .schemas import DentalMesh, Tooth3D
from .segmentation import (
    SegmentationAnalysisResult,
    SegmentationEvidence,
    SegmentationRequest,
    SegmentedTooth,
    ToothSegmentationProvider,
)
from .sources import DentalGeometrySource, GeometryProvision

#: Cap on real meshes surfaced per scene — bounds the payload while the
#: viewer renders one active mesh; raising it is a one-line change.
MAX_SCENE_MESHES = 8

# DICOM Part 10 CT only; Phase 5.1 never decodes Pixel Data.
SUPPORTED_DICOM_EXTENSIONS = frozenset({"dcm", "dicom"})
ACCEPTED_DICOM_MIMES = frozenset({DICOM_MEDIA_MIME, "application/octet-stream"})
DICOMDIR_SOP_CLASS_UID = "1.2.840.10008.1.3.10"
MAX_CBCT_INSTANCES = 2048
MAX_CBCT_SERIES = 32

_DICOM_HEADER_TAGS = [
    "Modality",
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "FrameOfReferenceUID",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "PixelSpacing",
    "SliceThickness",
    "ImagePositionPatient",
    "ImageOrientationPatient",
    "Manufacturer",
    "ManufacturerModelName",
]

_T = TypeVar("_T")


def _required_text(dataset, name: str) -> str:
    value = str(getattr(dataset, name, "") or "").strip()
    if not value:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MISSING_METADATA,
            f"required DICOM attribute {name} is missing",
        )
    return value


def _optional_text(dataset, name: str) -> str | None:
    value = str(getattr(dataset, name, "") or "").strip()
    return value or None


def _optional_vector(dataset, name: str, length: int) -> tuple[float, ...] | None:
    value = getattr(dataset, name, None)
    if value is None:
        return None
    try:
        converted = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            f"DICOM attribute {name} is not numeric",
        ) from exc
    if len(converted) != length:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            f"DICOM attribute {name} must contain {length} values",
        )
    return converted


def _optional_positive_float(dataset, name: str) -> float | None:
    value = getattr(dataset, name, None)
    if value in (None, ""):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            f"DICOM attribute {name} is not numeric",
        ) from exc
    if converted <= 0:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            f"DICOM attribute {name} must be positive",
        )
    return converted


def _read_dicom_metadata(data: bytes) -> DicomInstanceMetadata:
    """Parse a bounded set of geometry tags without reading Pixel Data or PHI."""
    if len(data) < 132 or data[128:132] != b"DICM":
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            "only DICOM Part 10 files with a DICM preamble are supported",
        )
    try:
        dataset = dcmread(
            BytesIO(data),
            stop_before_pixels=True,
            force=False,
            specific_tags=_DICOM_HEADER_TAGS,
        )
    except (InvalidDicomError, EOFError, OSError, ValueError) as exc:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            "the file header could not be parsed",
        ) from exc

    sop_class_uid = _required_text(dataset, "SOPClassUID")
    if sop_class_uid == DICOMDIR_SOP_CLASS_UID:
        raise DicomIngestionError(
            DicomIngestionErrorCode.UNSUPPORTED_DICOMDIR,
            "DICOMDIR file-set indexes are outside the Phase 5.1 ingestion scope",
        )
    modality = _required_text(dataset, "Modality").upper()
    if modality != "CT":
        raise DicomIngestionError(
            DicomIngestionErrorCode.UNSUPPORTED_MODALITY,
            f"modality {modality!r} is not supported; Phase 5.1 accepts CT only",
        )
    transfer_syntax_uid = str(getattr(dataset.file_meta, "TransferSyntaxUID", "") or "").strip()
    if not transfer_syntax_uid:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MISSING_METADATA,
            "required DICOM file-meta TransferSyntaxUID is missing",
        )

    try:
        return DicomInstanceMetadata(
            modality="CT",
            sop_class_uid=sop_class_uid,
            study_instance_uid=_required_text(dataset, "StudyInstanceUID"),
            series_instance_uid=_required_text(dataset, "SeriesInstanceUID"),
            sop_instance_uid=_required_text(dataset, "SOPInstanceUID"),
            transfer_syntax_uid=transfer_syntax_uid,
            frame_of_reference_uid=_optional_text(dataset, "FrameOfReferenceUID"),
            rows=int(_required_text(dataset, "Rows")),
            columns=int(_required_text(dataset, "Columns")),
            number_of_frames=int(getattr(dataset, "NumberOfFrames", 1) or 1),
            pixel_spacing_mm=_optional_vector(dataset, "PixelSpacing", 2),
            slice_thickness_mm=_optional_positive_float(dataset, "SliceThickness"),
            image_position_patient_mm=_optional_vector(dataset, "ImagePositionPatient", 3),
            image_orientation_patient=_optional_vector(dataset, "ImageOrientationPatient", 6),
            manufacturer=_optional_text(dataset, "Manufacturer"),
            manufacturer_model=_optional_text(dataset, "ManufacturerModelName"),
        )
    except DicomIngestionError:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise DicomIngestionError(
            DicomIngestionErrorCode.MALFORMED_DICOM,
            "required geometry metadata is invalid",
        ) from exc


def _media_download_url(document_id: UUID) -> str:
    return f"/api/v1/media/documents/{document_id}/download"


class PydicomMediaCbctAdapter:
    """pydicom header parser + existing-media storage adapter."""

    name = "pydicom-media"

    def __init__(self, db: AsyncSession, max_file_size: int) -> None:
        self._db = db
        self._max_file_size = max_file_size

    async def ingest(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        request: DicomIngestionRequest,
    ) -> DicomIngestionReceipt:
        if not request.data:
            raise DicomIngestionError(DicomIngestionErrorCode.EMPTY_FILE, "no content received")
        if len(request.data) > self._max_file_size:
            raise DicomIngestionError(
                DicomIngestionErrorCode.TOO_LARGE,
                f"file exceeds the {self._max_file_size // (1024 * 1024)}MB limit",
            )

        extension = request.filename.rsplit(".", 1)[1].lower() if "." in request.filename else ""
        if extension not in SUPPORTED_DICOM_EXTENSIONS:
            raise DicomIngestionError(
                DicomIngestionErrorCode.UNSUPPORTED_EXTENSION,
                f".{extension or '(none)'} is not supported; use .dcm or .dicom",
            )
        declared_mime = (request.content_type or "").split(";", 1)[0].strip().lower()
        if declared_mime and declared_mime not in ACCEPTED_DICOM_MIMES:
            raise DicomIngestionError(
                DicomIngestionErrorCode.MIME_MISMATCH,
                f"{declared_mime!r} is not a DICOM upload MIME",
            )

        metadata = _read_dicom_metadata(request.data)

        # Media owns bytes, paths, archival and authorized downloads. The
        # normalized catalog metadata uses its existing JSON extensibility
        # field, so Phase 5.1 creates neither a table nor a storage path.
        from app.modules.media.service import DocumentService

        document = await DocumentService.create_document(
            db=self._db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            file_data=request.data,
            original_filename=request.filename,
            mime_type=DICOM_MEDIA_MIME,
            document_type="other",
            title=request.title or request.filename,
            media_kind="document",
            tags=["dental-3d", "cbct", "dicom"],
        )
        document.extra_data = {
            **(document.extra_data or {}),
            DICOM_METADATA_KEY: {
                "schema_version": 1,
                "metadata": metadata.model_dump(mode="json"),
            },
        }
        await self._db.flush()
        return DicomIngestionReceipt(
            document_id=document.id,
            download_url=_media_download_url(document.id),
            metadata=metadata,
        )


def default_cbct_ingestion_port(db: AsyncSession) -> DicomIngestionPort:
    """Composition root for the replaceable Phase 5.1 ingestion adapter."""
    return PydicomMediaCbctAdapter(db, settings.STORAGE_MAX_FILE_SIZE)


# ---------------------------------------------------------------------------
# Synthetic source (Phase 1 behaviour behind the port)
# ---------------------------------------------------------------------------


def synthesise_teeth(records: list[ToothRecord]) -> list[Tooth3D]:
    """Build the default tooth list from odontogram records.

    Starts from the full permanent dentition so the viewer always has a
    complete arch to render, then overlays recorded conditions. Extra
    deciduous records are appended (mixed dentition support).
    """
    by_number = {r.tooth_number: r for r in records}
    teeth: list[Tooth3D] = []
    seen: set[int] = set()

    for number in PERMANENT_TEETH:
        record = by_number.get(number)
        condition = (record.general_condition if record else None) or ToothCondition.HEALTHY.value
        teeth.append(
            Tooth3D(
                tooth_number=number,
                present=condition != ToothCondition.MISSING.value,
                condition=condition,
            )
        )
        seen.add(number)

    # Deciduous records (51-85) that exist in the odontogram join as-is.
    for number, record in sorted(by_number.items()):
        if number in seen or number not in DECIDUOUS_TEETH:
            continue
        condition = record.general_condition or ToothCondition.HEALTHY.value
        teeth.append(
            Tooth3D(
                tooth_number=number,
                present=condition != ToothCondition.MISSING.value,
                condition=condition,
            )
        )

    # Stable numeric order (same as the merge path) so API consumers
    # never see two different orderings depending on persistence.
    teeth.sort(key=lambda t: t.tooth_number)
    return teeth


class SyntheticGeometrySource:
    """Phase 1's synthetic dentition, now behind the geometry port."""

    name = "synthetic"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def provide(self, clinic_id: UUID, patient_id: UUID) -> GeometryProvision:
        stmt = select(ToothRecord).where(
            ToothRecord.clinic_id == clinic_id,
            ToothRecord.patient_id == patient_id,
        )
        records = list((await self._db.execute(stmt)).scalars().all())
        return GeometryProvision(source="synthetic", teeth=synthesise_teeth(records))


# ---------------------------------------------------------------------------
# Intraoral scan source (Phase 2 — references into the media module)
# ---------------------------------------------------------------------------


def _mesh_descriptor(document: MediaDocument) -> DentalMesh:
    mesh_format = format_for_mime(document.mime_type)
    if mesh_format is None:  # pragma: no cover — query filters by mesh MIMEs
        raise ValueError(f"document {document.id} is not a mesh document")
    return DentalMesh(
        source="intraoral_scan",
        format=mesh_format,  # type: ignore[arg-type]
        document_id=document.id,
        label=document.title,
        file_size=document.file_size,
        uploaded_at=document.created_at,
        url=mesh_download_url(document.id),
    )


class IntraoralScanGeometrySource:
    """Discovers real scan meshes among the patient's media documents.

    Ownership is inherited from media: documents are filtered by
    ``clinic_id`` + ``patient_id`` + ``status='active'`` exactly like
    media's own list endpoints, so clinic isolation and archival
    semantics need no duplication here. Only documents stored with a
    canonical mesh MIME surface — arbitrary client files (PDFs,
    radiographs, …) are never mistaken for geometry.
    """

    name = "intraoral_scan"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def provide(self, clinic_id: UUID, patient_id: UUID) -> GeometryProvision:
        stmt = (
            select(MediaDocument)
            .where(
                MediaDocument.clinic_id == clinic_id,
                MediaDocument.patient_id == patient_id,
                MediaDocument.status == "active",
                MediaDocument.mime_type.in_(mesh_mimes()),
            )
            .order_by(MediaDocument.created_at.desc(), MediaDocument.id.desc())
            .limit(MAX_SCENE_MESHES)
        )
        documents = (await self._db.execute(stmt)).scalars().all()
        return GeometryProvision(
            source="intraoral_scan",
            meshes=[_mesh_descriptor(doc) for doc in documents],
        )


def _common(values: list[_T]) -> _T | None:
    """Return the common value when a series is internally consistent."""
    if not values:
        return None
    first = values[0]
    return first if all(value == first for value in values[1:]) else None


class CbctDicomGeometrySource:
    """Discover normalized CBCT/DICOM series in patient-owned media.

    Only documents written by the Phase 5.1 adapter are included. Stored
    bytes are never opened here, malformed metadata is ignored defensively,
    and media archival plus clinic/patient isolation remain authoritative.
    """

    name = "cbct"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def provide(self, clinic_id: UUID, patient_id: UUID) -> GeometryProvision:
        stmt = (
            select(MediaDocument)
            .where(
                MediaDocument.clinic_id == clinic_id,
                MediaDocument.patient_id == patient_id,
                MediaDocument.status == "active",
                MediaDocument.mime_type == DICOM_MEDIA_MIME,
            )
            .order_by(MediaDocument.created_at.desc(), MediaDocument.id.desc())
            .limit(MAX_CBCT_INSTANCES + 1)
        )
        documents = list((await self._db.execute(stmt)).scalars().all())
        instance_catalog_truncated = len(documents) > MAX_CBCT_INSTANCES
        documents = documents[:MAX_CBCT_INSTANCES]

        grouped: dict[tuple[str, str], list[tuple[MediaDocument, DicomInstanceMetadata]]] = {}
        for document in documents:
            envelope = (document.extra_data or {}).get(DICOM_METADATA_KEY)
            payload = envelope.get("metadata") if isinstance(envelope, dict) else None
            if not isinstance(payload, dict):
                continue
            try:
                metadata = DicomInstanceMetadata.model_validate(payload)
            except ValidationError:
                continue
            key = (metadata.study_instance_uid, metadata.series_instance_uid)
            grouped.setdefault(key, []).append((document, metadata))

        series_catalog_truncated = len(grouped) > MAX_CBCT_SERIES
        catalog_truncated = instance_catalog_truncated or series_catalog_truncated
        series: list[CbctSeriesDescriptor] = []
        for (study_uid, series_uid), instances in grouped.items():
            docs = [document for document, _ in instances]
            metadata = [item for _, item in instances]
            series.append(
                CbctSeriesDescriptor(
                    study_instance_uid=study_uid,
                    series_instance_uid=series_uid,
                    frame_of_reference_uid=_common(
                        [item.frame_of_reference_uid for item in metadata]
                    ),
                    document_ids=[document.id for document in docs],
                    instance_count=len(instances),
                    frame_count=sum(item.number_of_frames for item in metadata),
                    rows=_common([item.rows for item in metadata]),
                    columns=_common([item.columns for item in metadata]),
                    pixel_spacing_mm=_common([item.pixel_spacing_mm for item in metadata]),
                    slice_thickness_mm=_common([item.slice_thickness_mm for item in metadata]),
                    manufacturer=_common([item.manufacturer for item in metadata]),
                    manufacturer_model=_common([item.manufacturer_model for item in metadata]),
                    latest_uploaded_at=max(document.created_at for document in docs),
                    catalog_truncated=catalog_truncated,
                )
            )
        series.sort(key=lambda item: item.latest_uploaded_at, reverse=True)
        return GeometryProvision(source="cbct", cbct_series=series[:MAX_CBCT_SERIES])


def default_sources(db: AsyncSession) -> list[DentalGeometrySource]:
    """Composition root: the installed geometry providers, in priority order.

    Order matters — the first source that provides teeth defines the
    default dentition (synthetic today); meshes from every source are
    aggregated. New sources are appended here and nowhere else.
    """
    return [
        SyntheticGeometrySource(db),
        IntraoralScanGeometrySource(db),
        CbctDicomGeometrySource(db),
    ]


# ---------------------------------------------------------------------------
# Tooth segmentation provider (Phase 3 — deterministic, rule-based)
# ---------------------------------------------------------------------------


def _arch_region(tooth_number: int) -> str:
    """FDI quadrant + size category, e.g. ``Q1-molar`` (display evidence)."""
    quadrant, units = divmod(tooth_number, 10)
    if units <= 2:
        category = "incisor"
    elif units == 3:
        category = "canine"
    elif units <= 5:
        category = "premolar"
    else:
        category = "molar"
    return f"Q{quadrant}-{category}"


class ArchPartitionSegmentationProvider:
    """Deterministic arch-partition analysis — the Phase 3 engine.

    **This is not a medical AI model.** It is an explicitly rule-based
    foundation behind the :class:`ToothSegmentationProvider` port so
    the full pipeline (contracts, persistence, dentist review, UI) is
    exercisable end-to-end today; swapping in a real ML adapter later
    implements the same port and nothing else changes (ADR 0021).

    Rules (fixed, no randomness, no environment reads):

    - ``missing`` — the odontogram records the tooth as absent
      (``present=False``). Confidence 1.0 in the *status* (the record
      is the source of truth), basis ``odontogram_record``.
    - ``segmented`` — tooth present and healthy. Confidence 0.9 when
      real scan meshes back the scene (basis ``mesh_backed``), 0.75
      from the odontogram-driven synthetic arch alone (basis
      ``arch_position``). Deciduous teeth present: 0.7 — mixed
      dentition geometry is the least constrained case.
    - ``uncertain`` — tooth present but carries a restoration/finding
      condition (crown, implant, fracture, …): restorations change the
      observable geometry, so the proposal is flagged for the dentist.
      Confidence 0.5, basis ``odontogram_record``.

    Every proposal carries evidence (arch region, backing document
    ids, rule note). The schema pins ``is_clinical=False`` and
    ``requires_review=True`` — this provider cannot claim otherwise.
    """

    name = "arch-partition"
    input_kind = "scene"  # type: ignore[assignment]  # literal matches the port

    async def segment(self, request: SegmentationRequest) -> SegmentationAnalysisResult:
        backing = [m.document_id for m in request.meshes if m.document_id is not None]
        teeth: list[SegmentedTooth] = []

        for tooth in request.teeth:
            region = _arch_region(tooth.tooth_number)
            if not tooth.present:
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="missing",
                        confidence=1.0,
                        evidence=SegmentationEvidence(
                            basis="odontogram_record",
                            arch_region=region,
                            note="odontogram ToothRecord marks the tooth absent",
                        ),
                    )
                )
                continue

            deciduous = tooth.tooth_number >= 51
            if tooth.condition != "healthy":
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="uncertain",
                        confidence=0.5,
                        evidence=SegmentationEvidence(
                            basis="odontogram_record",
                            arch_region=region,
                            backing_documents=backing,
                            note=f"recorded condition '{tooth.condition}' alters geometry",
                        ),
                    )
                )
            elif backing:
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="segmented",
                        confidence=0.9,
                        evidence=SegmentationEvidence(
                            basis="mesh_backed",
                            arch_region=region,
                            backing_documents=backing,
                            note="arch position backed by real scan geometry",
                        ),
                    )
                )
            else:
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="segmented",
                        confidence=0.7 if deciduous else 0.75,
                        evidence=SegmentationEvidence(
                            basis="arch_position",
                            arch_region=region,
                            note="synthetic arch partition (no scan geometry yet)",
                        ),
                    )
                )

        teeth.sort(key=lambda t: t.tooth_number)
        return SegmentationAnalysisResult(
            provider=self.name,
            method="deterministic-arch-partition-v0",
            teeth=teeth,
            performed_at=request.performed_at,
        )


def default_segmentation_provider() -> ToothSegmentationProvider:
    """Composition root for segmentation — the installed engine.

    Replacing the rule-based analysis with a real ML model means
    returning a different ``ToothSegmentationProvider`` here (and only
    here); the service, contracts, persistence and UI are untouched.
    """
    return ArchPartitionSegmentationProvider()


def default_nerve_provider(db: AsyncSession) -> NerveDetectionProvider:
    """Return the Phase 5.2 CBCT provider; never a simulated substitute."""
    from .nerve_inference import default_cbct_nerve_provider

    return default_cbct_nerve_provider(db)
