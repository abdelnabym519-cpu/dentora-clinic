"""File validation utilities."""

from fastapi import HTTPException, UploadFile

from app.config import settings

# Document types enum
DOCUMENT_TYPES = ["consent", "id_scan", "insurance", "report", "referral", "other"]

# Modern image formats not in the default config allowlist but commonly
# uploaded from clinical phones / tablets. The base allowlist covers
# JPEG / PNG / PDF; we extend for HEIC (iOS), WebP and GIF so the photo
# gallery accepts them without per-clinic config changes.
_PHOTO_MIME_EXTRA = frozenset(
    {
        "image/heic",
        "image/heif",
        "image/webp",
        "image/gif",
    }
)


async def read_capped_upload(file: UploadFile, *, chunk_size: int = 1 << 20) -> bytes:
    """Read an upload enforcing ``STORAGE_MAX_FILE_SIZE`` on actual bytes.

    ``validate_file_size`` can only trust the client-supplied
    ``Content-Length`` header (often absent on chunked multipart bodies),
    so both upload endpoints must read through this helper: it streams in
    1 MiB chunks and aborts with 413 before an oversized body can exhaust
    worker memory or shared disk and degrade every other clinic.
    """
    cap = settings.STORAGE_MAX_FILE_SIZE
    buf = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        buf += chunk
        if len(buf) > cap:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds limit of {cap // (1024 * 1024)}MB",
            )
    return bytes(buf)


def validate_file_size(file: UploadFile, content_length: int | None = None) -> None:
    """Validate file size against limit.

    Args:
        file: Uploaded file
        content_length: Content-Length header value (if available)

    Raises:
        HTTPException: If file exceeds size limit
    """
    max_size = settings.STORAGE_MAX_FILE_SIZE

    if content_length and content_length > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds limit of {max_size // (1024 * 1024)}MB",
        )


def validate_mime_type(file: UploadFile) -> str:
    """Validate and return MIME type.

    Args:
        file: Uploaded file

    Returns:
        Validated MIME type

    Raises:
        HTTPException: If MIME type not allowed
    """
    allowed = set(settings.storage_allowed_mime_types_list) | _PHOTO_MIME_EXTRA
    content_type = file.content_type or "application/octet-stream"

    if content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{content_type}' not allowed. Allowed: {', '.join(sorted(allowed))}",
        )

    return content_type


def validate_document_type(document_type: str) -> None:
    """Validate document type.

    Args:
        document_type: Document type to validate

    Raises:
        HTTPException: If document type invalid
    """
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document type. Allowed: {', '.join(DOCUMENT_TYPES)}",
        )


_MAX_EXTENSION_LENGTH = 10


def get_file_extension(filename: str) -> str:
    """Extract a sanitized file extension from a filename.

    The result feeds server-generated storage paths, so it must never
    carry path separators (``../../x`` / ``sub/dir`` smuggled through a
    crafted ``original_filename`` would otherwise escape the intended
    prefix or create attacker-chosen subdirectories) nor unbounded
    attacker-controlled length. Only ``[a-z0-9]`` up to
    ``_MAX_EXTENSION_LENGTH`` chars survive; anything else yields ``""``
    and the caller stores the object extensionless.

    Args:
        filename: Original filename

    Returns:
        Sanitized extension without dot (e.g., "pdf")
    """
    if "." not in filename:
        return ""
    raw = filename.rsplit(".", 1)[1].lower()
    cleaned = "".join(ch for ch in raw if ch.isascii() and ch.isalnum())
    return cleaned[:_MAX_EXTENSION_LENGTH]


def content_disposition_filename(original_filename: str) -> str:
    """Build a safe ``Content-Disposition`` header value for a download.

    ``original_filename`` is user-controlled. Interpolating it raw inside
    ``filename="..."`` lets quotes break out of the parameter and CR/LF
    bytes (rejected by h11 with a 500, or worse, smuggled through proxies)
    corrupt the response. This helper strips CR/LF, quotes and backslashes
    for the legacy ``filename`` parameter and appends an RFC 5987
    ``filename*`` parameter so non-ASCII names (common in Spanish
    filenames) still download with their real name.
    """
    from urllib.parse import quote

    safe = (original_filename or "download").replace("\r", "").replace("\n", "")
    safe = safe.replace("\\", "").replace('"', "")
    safe = safe.strip() or "download"
    ascii_fallback = "".join(ch for ch in safe if ch.isascii()) or "download"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe)}"
