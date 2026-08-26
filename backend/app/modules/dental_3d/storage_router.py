"""Bounded upload routes for Dental 3D binary ingestion."""

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
from .schemas import DentalMesh
from .service import DentalMeshService

router = APIRouter()


async def _ensure_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> None:
    stmt = select(Patient).where(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
        Patient.status != "archived",
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")


async def _read_bounded(file: UploadFile) -> bytes:
    """Read at most max+1 bytes so an oversized request never fills process RAM."""

    return await file.read(settings.STORAGE_MAX_FILE_SIZE + 1)


@router.post(
    "/patients/{patient_id}/meshes",
    response_model=ApiResponse[DentalMesh],
    status_code=status.HTTP_201_CREATED,
)
async def upload_patient_mesh_bounded(
    patient_id: UUID,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)] = None,
    _: Annotated[None, Depends(require_permission("dental_3d.write"))] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ApiResponse[DentalMesh]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    data = await _read_bounded(file)
    if len(data) > settings.STORAGE_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"too_large: maximum file size is {settings.STORAGE_MAX_FILE_SIZE} bytes",
        )
    try:
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
async def upload_patient_dicom_instance_bounded(
    patient_id: UUID,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)] = None,
    _: Annotated[None, Depends(require_permission("dental_3d.write"))] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ApiResponse[DicomIngestionReceipt]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    data = await _read_bounded(file)
    if len(data) > settings.STORAGE_MAX_FILE_SIZE:
        error = DicomIngestionError(
            code=DicomIngestionErrorCode.TOO_LARGE,
            detail=f"maximum file size is {settings.STORAGE_MAX_FILE_SIZE} bytes",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    try:
        request = DicomIngestionRequest(
            filename=file.filename or "scan",
            content_type=file.content_type,
            data=data,
            title=title,
        )
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
