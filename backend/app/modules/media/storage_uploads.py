"""Application service for authorized direct S3 document uploads."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.events import EventType, event_bus

from .models import Document
from .service import DocumentService
from .storage import CompletedPart, MultipartUpload, StorageBackend, get_storage_backend
from .validation import validate_document_type


class ObjectUploadService:
    """Reserve DB metadata first, then activate it only after object verification."""

    @staticmethod
    def _storage() -> StorageBackend:
        storage = get_storage_backend()
        if not storage.is_object_storage or not storage.supports_presigned_urls:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Direct object upload requires STORAGE_BACKEND=s3",
            )
        return storage

    @staticmethod
    def _validate_request(*, document_type: str, mime_type: str, file_size: int) -> None:
        validate_document_type(document_type)
        allowed = set(settings.storage_allowed_mime_types_list)
        if mime_type not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Direct upload MIME type is not allowed for the document endpoint",
            )
        if file_size <= 0:
            raise HTTPException(status_code=400, detail="File must not be empty")
        if file_size > settings.STORAGE_MAX_FILE_SIZE:
            max_mb = settings.STORAGE_MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(status_code=400, detail=f"File size exceeds limit of {max_mb}MB")

    @staticmethod
    async def _reserve(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        original_filename: str,
        mime_type: str,
        file_size: int,
        checksum_sha256: str,
        document_type: str,
        title: str,
        description: str | None,
        upload_mode: str,
    ) -> Document:
        ObjectUploadService._validate_request(
            document_type=document_type,
            mime_type=mime_type,
            file_size=file_size,
        )
        storage_path = DocumentService.generate_storage_path(
            clinic_id, patient_id, original_filename
        )
        document = Document(
            clinic_id=clinic_id,
            patient_id=patient_id,
            document_type=document_type,
            title=title,
            description=description,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size=file_size,
            media_kind="document",
            media_category=None,
            media_subtype=None,
            tags=[],
            extra_data={
                "object_upload": {
                    "mode": upload_mode,
                    "state": "pending",
                    "expected_size": file_size,
                    "expected_sha256": checksum_sha256.lower(),
                }
            },
            uploaded_by=user_id,
            status="pending_upload",
        )
        db.add(document)
        await db.flush()
        return document

    @staticmethod
    async def create_presigned_upload(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        original_filename: str,
        mime_type: str,
        file_size: int,
        checksum_sha256: str,
        document_type: str,
        title: str,
        description: str | None,
    ) -> tuple[Document, str, dict[str, str]]:
        storage = ObjectUploadService._storage()
        document = await ObjectUploadService._reserve(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            checksum_sha256=checksum_sha256,
            document_type=document_type,
            title=title,
            description=description,
            upload_mode="presigned_put",
        )
        upload_url = await storage.presign_upload(
            document.storage_path,
            expires_seconds=settings.S3_PRESIGN_EXPIRE_SECONDS,
            content_type=mime_type,
            checksum_sha256=checksum_sha256,
        )
        headers = {
            "Content-Type": mime_type,
            "x-amz-meta-sha256": checksum_sha256.lower(),
        }
        return document, upload_url, headers

    @staticmethod
    async def create_multipart_upload(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        original_filename: str,
        mime_type: str,
        file_size: int,
        checksum_sha256: str,
        document_type: str,
        title: str,
        description: str | None,
    ) -> Document:
        storage = ObjectUploadService._storage()
        if not storage.supports_multipart_upload:
            raise HTTPException(status_code=409, detail="Multipart upload is not supported")
        document = await ObjectUploadService._reserve(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            checksum_sha256=checksum_sha256,
            document_type=document_type,
            title=title,
            description=description,
            upload_mode="multipart",
        )
        upload = await storage.create_multipart_upload(
            document.storage_path,
            content_type=mime_type,
            checksum_sha256=checksum_sha256,
        )
        envelope = dict(document.extra_data or {})
        object_upload = dict(envelope.get("object_upload") or {})
        object_upload["upload_id"] = upload.upload_id
        envelope["object_upload"] = object_upload
        document.extra_data = envelope
        await db.flush()
        return document

    @staticmethod
    async def presign_part(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        document_id: UUID,
        part_number: int,
    ) -> str:
        storage = ObjectUploadService._storage()
        document = await ObjectUploadService._pending_document(db, clinic_id, document_id)
        metadata = ObjectUploadService._upload_metadata(document)
        if metadata.get("mode") != "multipart" or not metadata.get("upload_id"):
            raise HTTPException(status_code=409, detail="Document is not a multipart upload")
        upload = MultipartUpload(key=document.storage_path, upload_id=str(metadata["upload_id"]))
        return await storage.presign_multipart_part(
            upload,
            part_number=part_number,
            expires_seconds=settings.S3_PRESIGN_EXPIRE_SECONDS,
        )

    @staticmethod
    async def complete_presigned_upload(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        document_id: UUID,
    ) -> Document:
        storage = ObjectUploadService._storage()
        document = await ObjectUploadService._pending_document(db, clinic_id, document_id)
        metadata = ObjectUploadService._upload_metadata(document)
        if metadata.get("mode") != "presigned_put":
            raise HTTPException(status_code=409, detail="Document is not a presigned PUT upload")
        return await ObjectUploadService._verify_and_activate(db, storage, document)

    @staticmethod
    async def complete_multipart(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        document_id: UUID,
        parts: list[CompletedPart],
    ) -> Document:
        storage = ObjectUploadService._storage()
        document = await ObjectUploadService._pending_document(db, clinic_id, document_id)
        metadata = ObjectUploadService._upload_metadata(document)
        upload_id = metadata.get("upload_id")
        if metadata.get("mode") != "multipart" or not upload_id:
            raise HTTPException(status_code=409, detail="Document is not a multipart upload")
        upload = MultipartUpload(key=document.storage_path, upload_id=str(upload_id))
        try:
            await storage.complete_multipart_upload(upload, parts=parts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await ObjectUploadService._verify_and_activate(db, storage, document)

    @staticmethod
    async def abort_multipart(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        document_id: UUID,
    ) -> None:
        storage = ObjectUploadService._storage()
        document = await ObjectUploadService._pending_document(db, clinic_id, document_id)
        metadata = ObjectUploadService._upload_metadata(document)
        upload_id = metadata.get("upload_id")
        if metadata.get("mode") != "multipart" or not upload_id:
            raise HTTPException(status_code=409, detail="Document is not a multipart upload")
        await storage.abort_multipart_upload(
            MultipartUpload(key=document.storage_path, upload_id=str(upload_id))
        )
        document.status = "archived"
        envelope = dict(document.extra_data or {})
        object_upload = dict(envelope.get("object_upload") or {})
        object_upload["state"] = "aborted"
        envelope["object_upload"] = object_upload
        document.extra_data = envelope
        await db.flush()

    @staticmethod
    async def _pending_document(
        db: AsyncSession,
        clinic_id: UUID,
        document_id: UUID,
    ) -> Document:
        document = await DocumentService.get_document(db, clinic_id, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if document.status != "pending_upload":
            raise HTTPException(status_code=409, detail="Document upload is not pending")
        return document

    @staticmethod
    def _upload_metadata(document: Document) -> dict:
        metadata = (document.extra_data or {}).get("object_upload")
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=409, detail="Object upload metadata is missing")
        return metadata

    @staticmethod
    async def _verify_and_activate(
        db: AsyncSession,
        storage: StorageBackend,
        document: Document,
    ) -> Document:
        metadata = ObjectUploadService._upload_metadata(document)
        expected_size = int(metadata["expected_size"])
        expected_sha = str(metadata["expected_sha256"]).lower()
        try:
            info = await storage.stat(document.storage_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail="Uploaded object was not found") from exc
        if info.size != expected_size:
            await ObjectUploadService._mark_failed(
                db, document, f"size_mismatch:{info.size}:{expected_size}"
            )
            raise HTTPException(status_code=400, detail="Uploaded object size does not match declaration")

        digest = hashlib.sha256()
        async for chunk in storage.iter_chunks(
            document.storage_path, chunk_size=settings.STORAGE_STREAM_CHUNK_SIZE
        ):
            digest.update(chunk)
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            await ObjectUploadService._mark_failed(db, document, "checksum_mismatch")
            raise HTTPException(status_code=400, detail="Uploaded object checksum verification failed")

        envelope = dict(document.extra_data or {})
        object_upload = dict(envelope.get("object_upload") or {})
        object_upload.update(
            {
                "state": "verified",
                "verified_size": info.size,
                "verified_sha256": actual_sha,
            }
        )
        object_upload.pop("upload_id", None)
        envelope["object_upload"] = object_upload
        document.extra_data = envelope
        document.status = "active"
        await db.flush()
        await event_bus.publish(
            EventType.DOCUMENT_UPLOADED,
            {
                "document_id": str(document.id),
                "clinic_id": str(document.clinic_id),
                "patient_id": str(document.patient_id),
                "title": document.title,
                "document_type": document.document_type,
                "media_kind": document.media_kind,
                "media_category": document.media_category,
                "media_subtype": document.media_subtype,
            },
        )
        return document

    @staticmethod
    async def _mark_failed(db: AsyncSession, document: Document, reason: str) -> None:
        envelope = dict(document.extra_data or {})
        object_upload = dict(envelope.get("object_upload") or {})
        object_upload.update({"state": "verification_failed", "failure": reason})
        envelope["object_upload"] = object_upload
        document.extra_data = envelope
        await db.flush()
