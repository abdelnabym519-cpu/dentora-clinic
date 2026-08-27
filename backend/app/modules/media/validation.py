"""File validation utilities."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from fastapi import HTTPException, UploadFile

from app.config import settings

DOCUMENT_TYPES = ["consent", "id_scan", "insurance", "report", "referral", "other"]
UPLOAD_CHUNK_SIZE = 1024 * 1024
_SAFE_EXTENSION_RE = re.compile(r"^[a-z0-9]{1,16}$")

_PHOTO_MIME_EXTRA = frozenset(
    {
        "image/heic",
        "image/heif",
        "image/webp",
        "image/gif",
    }
)


def _too_large(max_size: int) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=f"File size exceeds limit of {max_size // (1024 * 1024)}MB",
    )


def validate_file_size(file: UploadFile, content_length: int | None = None) -> None:
    """Deterministically validate the parsed upload size when available.

    Starlette tracks ``UploadFile.size`` while parsing multipart bodies. The
    optional content length remains a compatibility fallback for callers that
    construct UploadFile instances without a size. Streaming readers below
    enforce the same limit again while consuming bytes, so a missing or
    incorrect declared size cannot bypass the configured maximum.
    """
    max_size = settings.STORAGE_MAX_FILE_SIZE
    parsed_size = getattr(file, "size", None)
    measured = parsed_size if parsed_size is not None else content_length
    if measured is not None and measured > max_size:
        raise _too_large(max_size)


async def iter_upload_chunks(
    file: UploadFile,
    *,
    max_size: int | None = None,
    chunk_size: int = UPLOAD_CHUNK_SIZE,
) -> AsyncIterator[bytes]:
    """Yield upload bytes incrementally while enforcing a hard byte limit."""
    limit = settings.STORAGE_MAX_FILE_SIZE if max_size is None else max_size
    if limit <= 0:
        raise ValueError("max_size must be positive")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    total = 0
    while chunk := await file.read(chunk_size):
        total += len(chunk)
        if total > limit:
            raise _too_large(limit)
        yield chunk


async def read_upload_bytes_limited(
    file: UploadFile,
    *,
    max_size: int | None = None,
) -> bytes:
    """Compatibility helper for validators that still require a byte payload."""
    data = bytearray()
    async for chunk in iter_upload_chunks(file, max_size=max_size):
        data.extend(chunk)
    return bytes(data)


def validate_mime_type(file: UploadFile) -> str:
    """Validate and return MIME type."""
    allowed = set(settings.storage_allowed_mime_types_list) | _PHOTO_MIME_EXTRA
    content_type = file.content_type or "application/octet-stream"

    if content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{content_type}' not allowed. Allowed: {', '.join(sorted(allowed))}",
        )

    return content_type


def validate_document_type(document_type: str) -> None:
    """Validate document type."""
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document type. Allowed: {', '.join(DOCUMENT_TYPES)}",
        )


def get_file_extension(filename: str) -> str:
    """Return a safe extension only; never let filenames shape object paths."""
    if "." not in filename:
        return ""
    extension = filename.rsplit(".", 1)[1].lower()
    return extension if _SAFE_EXTENSION_RE.fullmatch(extension) else ""
