"""Dental 3D FastAPI router.

Mounted at ``/api/v1/dental_3d/`` by the module loader. Thin router —
logic lives in the service.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.patients.models import Patient

from .cbct import (
    DicomIngestionError,
    DicomIngestionErrorCode,
    DicomIngestionReceipt,
    DicomIngestionRequest,
)
from .cbct_service import CbctIngestionService
from .infrastructure import default_cbct_ingestion_port
from .meshfiles import MeshUploadError
from .nerve import NerveDetectionAnalysisResponse, NerveDetectionRunRequest, NerveReviewUpdate
from .registration import AlignmentResult, AlignmentReviewUpdate, AlignmentRunRequest
from .registration_service import AlignmentError, DentalAlignmentService
from .schemas import DentalMesh, DentalSceneResponse, DentalSceneUpdate
from .segmentation import SegmentationAnalysisResponse, SegmentationReviewUpdate
from .service import (
    DentalMeshService,
    DentalNerveService,
    DentalSceneService,
    DentalSegmentationService,
    NerveError,
    SegmentationError,
)

router = APIRouter()
_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _ensure_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> None:
    """Mirror the odontogram pattern: 404 if patient is missing/archived."""
    stmt = select(Patient).where(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
        Patient.status != "archived",
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")


async def _read_mesh_upload(file: UploadFile) -> bytes:
    """Read mesh validation input with a deterministic configured byte ceiling."""
    max_size = settings.STORAGE_MAX_FILE_SIZE
    parsed_size = getattr(file, "size", None)
    if parsed_size is not None and parsed_size > max_size:
        raise MeshUploadError(
            f"too_large: file exceeds the {max_size // (1024 * 1024)}MB limit"
        )

    data = bytearray()
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
        total += len(chunk)
        if total > max_size:
            raise MeshUploadError(
                f"too_large: file exceeds the {max_size // (1024 * 1024)}MB limit"
            )
        data.extend(chunk)
    return bytes(data)


async def _read_dicom_upload(file: UploadFile) -> bytes:
    """Read DICOM header-validation input with the same hard storage upload limit."""
    max_size = settings.STORAGE_MAX_FILE_SIZE
    parsed_size = getattr(file, "size", None)
    if parsed_size is not None and parsed_size > max_size:
        raise DicomIngestionError(
            DicomIngestionErrorCode.TOO_LARGE,
            f"file exceeds the {max_size // (1024 * 1024)}MB limit",
        )

    data = bytearray()
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
        total += len(chunk)
        if total > max_size:
            raise DicomIngestionError(
                DicomIngestionErrorCode.TOO_LARGE,
                f"file exceeds the {max_size // (1024 * 1024)}MB limit",
            )
        data.extend(chunk)
    return bytes(data)


@router.get(
    "/patients/{patient_id}/scene",
    response_model=ApiResponse[DentalSceneResponse],
)
async def get_patient_scene(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalSceneResponse]:
    """Return the patient's 3D scene (synthesised + persisted view state)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    scene = await DentalSceneService.get_for_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=scene)


@router.put(
    "/patients/{patient_id}/scene",
    response_model=ApiResponse[DentalSceneResponse],
)
async def save_patient_scene(
    patient_id: UUID,
    data: DentalSceneUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalSceneResponse]:
    """Persist per-tooth 3D view state (full replace)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    scene = await DentalSceneService.save_for_patient(
        db, ctx.clinic_id, patient_id, ctx.user_id, data
    )
    return ApiResponse(data=scene)


@router.post(
    "/patients/{patient_id}/meshes",
    response_model=ApiResponse[DentalMesh],
    status_code=status.HTTP_201_CREATED,
)
async def upload_patient_mesh(
    patient_id: UUID,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)] = None,
    _: Annotated[None, Depends(require_permission("dental_3d.write"))] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ApiResponse[DentalMesh]:
    """Ingest a real mesh file (STL / OBJ) as the patient's scan geometry.

    Validation (extension + MIME + content sniff + size) happens in the
    service; storage goes through the media module — this endpoint
    never touches the filesystem. Patient/clinic ownership is resolved
    server-side from the authenticated context.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)

    try:
        data = await _read_mesh_upload(file)
        mesh = await DentalMeshService.ingest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            filename=file.filename or "scan",
            content_type=file.content_type,
            data=data,
            title=title,
        )
    except MeshUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=mesh)


@router.post(
    "/patients/{patient_id}/cbct/dicom-instances",
    response_model=ApiResponse[DicomIngestionReceipt],
    status_code=status.HTTP_201_CREATED,
)
async def upload_patient_dicom_instance(
    patient_id: UUID,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)] = None,
    _: Annotated[None, Depends(require_permission("dental_3d.write"))] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ApiResponse[DicomIngestionReceipt]:
    """Validate/store one CT DICOM instance and return normalized metadata.

    The controller owns HTTP/auth concerns only. Parsing and storage are
    replaceable infrastructure behind the application port; no pixel decoding
    or clinical inference occurs in Phase 5.1.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        request = DicomIngestionRequest(
            filename=file.filename or "scan",
            content_type=file.content_type,
            data=await _read_dicom_upload(file),
            title=title,
        )
    except DicomIngestionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValidationError as exc:
        error = DicomIngestionError(
            code=DicomIngestionErrorCode.INVALID_REQUEST,
            detail="filename or content metadata is invalid",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from exc
    service = CbctIngestionService(default_cbct_ingestion_port(db))
    try:
        receipt = await service.ingest(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            request=request,
        )
    except DicomIngestionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=receipt)


@router.post(
    "/patients/{patient_id}/segmentation",
    response_model=ApiResponse[SegmentationAnalysisResponse],
    status_code=status.HTTP_201_CREATED,
)
async def run_patient_segmentation(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SegmentationAnalysisResponse]:
    """Run the automatic tooth-segmentation analysis for the patient's scene.

    The analysis is produced **server-side** by the configured
    provider (deterministic arch-partition in Phase 3 — not a medical
    AI model) and persisted with review state ``pending``. There is no
    endpoint that accepts a client-supplied segmentation result: the
    dentist-review workflow (input → analysis → evidence → review →
    decision) is the only path, and a review never alters odontogram
    records. Results are non-clinical decision support.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        analysis = await DentalSegmentationService.run_analysis(
            db, clinic_id=ctx.clinic_id, patient_id=patient_id, user_id=ctx.user_id
        )
    except SegmentationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ApiResponse(data=analysis)


@router.get(
    "/patients/{patient_id}/segmentation",
    response_model=ApiResponse[SegmentationAnalysisResponse],
)
async def get_patient_segmentation(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SegmentationAnalysisResponse]:
    """Return the patient's latest segmentation analysis (404 if never run)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    analysis = await DentalSegmentationService.latest_analysis(db, ctx.clinic_id, patient_id)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No segmentation analysis yet"
        )
    return ApiResponse(data=analysis)


@router.post(
    "/patients/{patient_id}/segmentation/{analysis_id}/review",
    response_model=ApiResponse[SegmentationAnalysisResponse],
)
async def review_patient_segmentation(
    patient_id: UUID,
    analysis_id: UUID,
    data: SegmentationReviewUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SegmentationAnalysisResponse]:
    """Record the dentist's review decision on a pending analysis.

    Accepting records the dentist's acknowledgement of the
    decision-support output — it never marks anything clinically
    completed and never writes to the odontogram. Re-reviewing a
    decided analysis is rejected (409).
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        analysis = await DentalSegmentationService.review_analysis(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            analysis_id=analysis_id,
            reviewer_id=ctx.user_id,
            payload=data,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    except SegmentationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=analysis)


@router.post(
    "/patients/{patient_id}/nerve-detection",
    response_model=ApiResponse[NerveDetectionAnalysisResponse],
    status_code=status.HTTP_201_CREATED,
)
async def run_patient_nerve_detection(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    data: NerveDetectionRunRequest | None = None,
) -> ApiResponse[NerveDetectionAnalysisResponse]:
    """Run the mandibular nerve-detection analysis for the patient's scene.

    The analysis is produced server-side from a patient-owned CBCT series by
    the configured Phase 5.2 inference service. An unavailable model or bad
    input is persisted as an explicit non-reviewable failure; Dentora never
    substitutes demo anatomy. There is no endpoint that accepts a
    client-supplied detection result: the dentist-review workflow
    (input → analysis → evidence → review → decision) is the only path,
    a review never approves an implant or surgical plan. Native DICOM-patient
    geometry is not aligned to teeth or surface scans in this phase.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        analysis = await DentalNerveService.run_detection(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            requested_series_instance_uid=(data.series_instance_uid if data else None),
        )
    except NerveError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ApiResponse(data=analysis)


@router.get(
    "/patients/{patient_id}/nerve-detection",
    response_model=ApiResponse[NerveDetectionAnalysisResponse],
)
async def get_patient_nerve_detection(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[NerveDetectionAnalysisResponse]:
    """Return the patient's latest nerve-detection analysis (404 if never run)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    analysis = await DentalNerveService.latest_analysis(db, ctx.clinic_id, patient_id)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No nerve detection analysis yet"
        )
    return ApiResponse(data=analysis)


@router.post(
    "/patients/{patient_id}/nerve-detection/{analysis_id}/review",
    response_model=ApiResponse[NerveDetectionAnalysisResponse],
)
async def review_patient_nerve_detection(
    patient_id: UUID,
    analysis_id: UUID,
    data: NerveReviewUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[NerveDetectionAnalysisResponse]:
    """Record the dentist's review decision on a pending analysis.

    Accepting records the dentist's acknowledgement of the
    decision-support output — it never marks anything clinically
    verified, never approves a plan, and never writes to the
    odontogram. Re-reviewing a decided analysis is rejected (409).
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        analysis = await DentalNerveService.review_analysis(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            analysis_id=analysis_id,
            reviewer_id=ctx.user_id,
            payload=data,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    except NerveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=analysis)


@router.post(
    "/patients/{patient_id}/alignment",
    response_model=ApiResponse[AlignmentResult],
    status_code=status.HTTP_201_CREATED,
)
async def run_patient_alignment(
    patient_id: UUID,
    data: AlignmentRunRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AlignmentResult]:
    """Run real patient-specific rigid IOS→CBCT registration.

    The server resolves patient-owned inputs, requires explicit IOS units,
    preserves the DICOM frame, and persists success or safe failure. A valid
    transform remains technical decision support until dentist review.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    result = await DentalAlignmentService.run_alignment(
        db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        user_id=ctx.user_id,
        request=data,
    )
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/alignment",
    response_model=ApiResponse[AlignmentResult],
)
async def get_patient_alignment(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AlignmentResult]:
    """Return the latest patient-specific alignment result."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    result = await DentalAlignmentService.latest_alignment(db, ctx.clinic_id, patient_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No patient alignment result yet",
        )
    return ApiResponse(data=result)


@router.post(
    "/patients/{patient_id}/alignment/{alignment_id}/review",
    response_model=ApiResponse[AlignmentResult],
)
async def review_patient_alignment(
    patient_id: UUID,
    alignment_id: UUID,
    data: AlignmentReviewUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AlignmentResult]:
    """Accept or reject one reviewable technical registration result."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalAlignmentService.review_alignment(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            alignment_id=alignment_id,
            reviewer_id=ctx.user_id,
            payload=data,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alignment not found")
    except AlignmentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
