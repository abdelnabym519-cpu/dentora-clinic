"""Scalable media delivery endpoints layered over the existing media API."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .service import DocumentService
from .storage import get_document_storage_backend

router = APIRouter()


class PresignedDownloadResponse(BaseModel):
    """Short-lived private object download URL."""

    url: HttpUrl
    expires_in_seconds: int


def _content_disposition(filename: str) -> str:
    safe = quote(filename, safe="")
    return f"attachment; filename*=UTF-8''{safe}"


@router.get("/documents/{document_id}/stream")
async def stream_document(
    document_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Stream an authorized document without materialising it fully in RAM."""
    document = await DocumentService.get_document(db, ctx.clinic_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage = get_document_storage_backend(document)
    try:
        info = await storage.stat(document.storage_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Object not found") from exc

    return StreamingResponse(
        storage.iter_bytes(document.storage_path),
        media_type=document.mime_type,
        headers={
            "Content-Length": str(info.size),
            "Content-Disposition": _content_disposition(document.original_filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/documents/{document_id}/presigned-download",
    response_model=ApiResponse[PresignedDownloadResponse],
)
async def presigned_document_download(
    document_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("media.documents.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PresignedDownloadResponse]:
    """Issue a short-lived private S3 GET URL after normal Dentora authorization."""
    document = await DocumentService.get_document(db, ctx.clinic_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage = get_document_storage_backend(document)
    config = getattr(storage, "config", None)
    expires = int(getattr(config, "presign_expiry_seconds", 0) or 0)
    if not storage.supports_presigned_urls or expires <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configured storage backend does not support presigned URLs",
        )

    url = await storage.presign_download(
        document.storage_path,
        expires_seconds=expires,
        content_disposition=_content_disposition(document.original_filename),
    )
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to create presigned download URL",
        )
    return ApiResponse(
        data=PresignedDownloadResponse(url=url, expires_in_seconds=expires),
    )
