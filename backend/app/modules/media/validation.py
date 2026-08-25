"""File validation utilities."""

from fastapi import HTTPException, UploadFile

from app.config import settings

DOCUMENT_TYPES = ["consent", "id_scan", "insurance", "report", "referral", "other"]

_PHOTO_MIME_EXTRA = frozenset(
    {
        "image/heic",
        "image/heif",
        "image/webp",
        "image/gif",
    }
)


def _uploaded_size(file: UploadFile) -> int | None:
    """Return the actual spooled upload size without trusting Content-Length."""

    size = getattr(file, "size", None)
    if isinstance(size, int):
        return size

    raw = getattr(file, "file", None)
    if raw is None or not hasattr(raw, "seek") or not hasattr(raw, "tell"):
        return None
    try:
        position = raw.tell()
        raw.seek(0, 2)
        actual = raw.tell()
        raw.seek(position)
        return int(actual)
    except (OSError, ValueError):
        return None


def validate_file_size(file: UploadFile, content_length: int | None = None) -> None:
    """Enforce the configured business upload limit against actual bytes.

    ``Content-Length`` is only an early-rejection hint.  Starlette's
    ``UploadFile.size`` (or the spooled file size fallback) is the source of
    truth, so omitting or lying about the request header cannot bypass the
    limit.
    """

    max_size = settings.STORAGE_MAX_FILE_SIZE
    candidates = [size for size in (content_length, _uploaded_size(file)) if size is not None]
    if candidates and max(candidates) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds limit of {max_size // (1024 * 1024)}MB",
        )


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
    """Validate administrative document type."""

    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document type. Allowed: {', '.join(DOCUMENT_TYPES)}",
        )


def get_file_extension(filename: str) -> str:
    """Extract a conservative lowercase extension without path semantics."""

    if "." not in filename:
        return ""
    raw = filename.rsplit(".", 1)[1].lower()
    if not raw or len(raw) > 16 or not raw.isalnum():
        return ""
    return raw
