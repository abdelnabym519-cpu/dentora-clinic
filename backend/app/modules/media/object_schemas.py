"""Schemas for server-authorized direct object-storage uploads."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .schemas import DocumentType


class ObjectUploadCreate(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    document_type: DocumentType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class PresignedUploadResponse(BaseModel):
    document_id: UUID
    upload_url: str
    method: Literal["PUT"] = "PUT"
    expires_seconds: int
    headers: dict[str, str]


class MultipartUploadResponse(BaseModel):
    document_id: UUID
    part_size: int
    expires_seconds: int


class MultipartPartResponse(BaseModel):
    part_number: int
    upload_url: str
    expires_seconds: int


class MultipartCompletedPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=255)


class MultipartCompleteRequest(BaseModel):
    parts: list[MultipartCompletedPart] = Field(min_length=1, max_length=10_000)


class ObjectUploadCompleteResponse(BaseModel):
    document_id: UUID
    status: Literal["active"] = "active"
    file_size: int
