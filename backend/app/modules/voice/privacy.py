"""Voice-specific audit sanitization."""

from __future__ import annotations

import re
from typing import Any

_REDACT_KEYS = {
    "query",
    "patient_name",
    "full_name",
    "first_name",
    "last_name",
    "phone",
    "mobile",
    "email",
    "dni",
    "nif",
    "content",
    "transcript",
}
_REDACT_SUFFIXES = ("patient_id", "document_id", "appointment_id")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


def sanitize_audit_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.casefold()
            if lowered in _REDACT_KEYS or lowered.endswith(_REDACT_SUFFIXES):
                out[key] = "[REDACTED]"
            else:
                out[key] = sanitize_audit_payload(item)
        return out
    if isinstance(value, list):
        return [sanitize_audit_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_audit_payload(item) for item in value]
    if isinstance(value, str):
        return _UUID_RE.sub("[REDACTED_UUID]", value)
    return value
