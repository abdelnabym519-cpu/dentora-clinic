"""Storage-aware media routes layered ahead of the legacy media router."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.patients.service import PatientService

from .object_schemas import (
    MultipartCompleteRequest,
    MultipartPartResponse,
    MultipartUploadResponse,
    ObjectUploadCompleteResponse,
    ObjectUploadCreate,
    PresignedUploadResponse,
)
from .service import DocumentService
from .storage import CompletedPart, get_storage_backend
from .storage_uploads import ObjectUploadService
from .thumbnails import MEDIUM_SUFFIX, THUMB_SUFFIX, is_thumbnailable

router = APIRouter()


def _safe_disposition(filename: str) -> str:
    clean = filename.replace("\r", "").replace("\n", "").replace('"', "")
    return f'attachment; filename="{clean or "download"}"'


@router.get("/documents/{document_id}/download")
async def download_document_streaming(
    document_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    variant: Literal["thumb", "medium", "full"] = Query(default="full"),
):
    """Authorize in PostgreSQL, then stream local bytes or redirect to private S3."""

    document = await DocumentService.get_document(db, ctx.clinic_id, document_id)
    if document is None or document.status != "active":
        raise HTTPException(status_code=404, detail="Document not found")

    storage = get_storage_backend()
    base_path = document.storage_path
    path = base_path
    media_type = document.mime_type
    if variant == "thumb" and is_thumbnailable(document.mime_type):
        path = f"{base_path}{THUMB_SUFFIX}"
        media_type = "image/jpeg"
    elif variant == "medium" and is_thumbnailable(document.mime_type):
        path = f"{base_path}{MEDIUM_SUFFIX}"
        media_type = "image/jpeg"

    if path != base_path and not await storage.exists(path):
        path = base_path
        media_type = document.mime_type

    disposition = _safe_disposition(document.original_filename) if variant == "full" else None
    if storage.supports_presigned_urls:
        try:
            url = await storage.presign_download(
                path,
                expires_seconds=settings.S3_PRESIGN_EXPIRE_SECONDS,
                response_content_type=media_type,
                response_content_disposition=disposition,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Stored object not found") from exc
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    try:
        info = await storage.stat(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Stored object not found") from exc
    headers = {"Content-Length": str(info.size)}
    if disposition:
        headers["Content-Disposition"] = disposition
    return StreamingResponse(
        storage.iter_chunks(path, chunk_size=settings.STORAGE_STREAM_CHUNK_SIZE),
        media_type=media_type,
        headers=headers,
    )


@router.post(
    "/patients/{patient_id}/object-uploads",
    response_model=ApiResponse[PresignedUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_object_upload(
    patient_id: UUID,
    data: ObjectUploadCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PresignedUploadResponse]:
    """Reserve metadata and return a PUT URL for a server-generated object key."""

    patient = await PatientService.get_patient(db, ctx.clinic_id, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    document, upload_url, headers = await ObjectUploadService.create_presigned_upload(
        db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        user_id=ctx.user_id,
        **data.model_dump(),
    )
    return ApiResponse(
        data=PresignedUploadResponse(
            document_id=document.id,
            upload_url=upload_url,
            expires_seconds=settings.S3_PRESIGN_EXPIRE_SECONDS,
            headers=headers,
        )
    )


@router.post(
    "/object-uploads/{document_id}/complete",
    response_model=ApiResponse[ObjectUploadCompleteResponse],
)
async def complete_object_upload(
    document_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ObjectUploadCompleteResponse]:
    document = await ObjectUploadService.complete_presigned_upload(
        db, clinic_id=ctx.clinic_id, document_id=document_id
    )
    return ApiResponse(
        data=ObjectUploadCompleteResponse(
            document_id=document.id,
            file_size=document.file_size,
        )
    )


@router.post(
    "/patients/{patient_id}/multipart-uploads",
    response_model=ApiResponse[MultipartUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_multipart_upload(
    patient_id: UUID,
    data: ObjectUploadCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MultipartUploadResponse]:
    patient = await PatientService.get_patient(db, ctx.clinic_id, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    document = await ObjectUploadService.create_multipart_upload(
        db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        user_id=ctx.user_id,
        **data.model_dump(),
    )
    return ApiResponse(
        data=MultipartUploadResponse(
            document_id=document.id,
            part_size=settings.S3_MULTIPART_PART_SIZE,
            expires_seconds=settings.S3_PRESIGN_EXPIRE_SECONDS,
        )
    )


@router.post(
    "/multipart-uploads/{document_id}/parts/{part_number}",
    response_model=ApiResponse[MultipartPartResponse],
)
async def create_multipart_part_url(
    document_id: UUID,
    part_number: int,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[MultipartPartResponse]:
    if part_number < 1 or part_number > 10_000:
        raise HTTPException(status_code=400, detail="part_number must be between 1 and 10000")
    upload_url = await ObjectUploadService.presign_part(
        db,
        clinic_id=ctx.clinic_id,
        document_id=document_id,
        part_number=part_number,
    )
    return ApiResponse(
        data=MultipartPartResponse(
            part_number=part_number,
            upload_url=upload_url,
            expires_seconds=settings.S3_PRESIGN_EXPIRE_SECONDS,
        )
    )


@router.post(
    "/multipart-uploads/{document_id}/complete",
    response_model=ApiResponse[ObjectUploadCompleteResponse],
)
async def complete_multipart_upload(
    document_id: UUID,
    data: MultipartCompleteRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ObjectUploadCompleteResponse]:
    parts = [CompletedPart(part_number=item.part_number, etag=item.etag) for item in data.parts]
    document = await ObjectUploadService.complete_multipart(
        db,
        clinic_id=ctx.clinic_id,
        document_id=document_id,
        parts=parts,
    )
    return ApiResponse(
        data=ObjectUploadCompleteResponse(
            document_id=document.id,
            file_size=document.file_size,
        )
    )


@router.delete(
    "/multipart-uploads/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def abort_multipart_upload(
    document_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await ObjectUploadService.abort_multipart(db, clinic_id=ctx.clinic_id, document_id=document_id)
