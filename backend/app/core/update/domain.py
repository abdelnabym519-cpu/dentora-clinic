"""Pure domain rules for trusted Dentora update metadata."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_ALLOWED = frozenset({"version", "package_url", "sha256", "size", "schema_revision", "requires_backup"})


class UpdateValidationError(ValueError):
    """Trusted update metadata failed validation."""


def _version_tuple(value: Any, *, installed: bool = False) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise UpdateValidationError(
            "Installed application version is invalid" if installed else "Update version is invalid"
        )
    match = _VERSION.fullmatch(value)
    if match is None:
        raise UpdateValidationError(
            "Installed application version is invalid" if installed else "Update version is invalid"
        )
    return tuple(int(part) for part in match.groups())


@dataclass(frozen=True)
class UpdateDescriptor:
    version: str
    package_url: str
    sha256: str
    size: int
    schema_revision: str
    requires_backup: bool

    @classmethod
    def from_dict(cls, value: Any) -> "UpdateDescriptor":
        if not isinstance(value, dict) or set(value) != _ALLOWED:
            raise UpdateValidationError("Update descriptor is incomplete or unsupported")
        version = value.get("version")
        package_url = value.get("package_url")
        sha256 = value.get("sha256")
        size = value.get("size")
        schema = value.get("schema_revision")
        requires_backup = value.get("requires_backup")
        _version_tuple(version)
        if not isinstance(package_url, str) or not package_url.startswith("https://"):
            raise UpdateValidationError("Update package URL must use HTTPS")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise UpdateValidationError("Update package SHA-256 is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise UpdateValidationError("Update package size is invalid")
        if not isinstance(schema, str) or not _SCHEMA.fullmatch(schema):
            raise UpdateValidationError("Update schema revision is invalid")
        if not isinstance(requires_backup, bool):
            raise UpdateValidationError("Update backup requirement is invalid")
        return cls(version, package_url, sha256, size, schema, requires_backup)

    def assert_upgrade_from(self, current_version: str) -> None:
        current = _version_tuple(current_version, installed=True)
        target = _version_tuple(self.version)
        if target <= current:
            raise UpdateValidationError("Update must be a strict upgrade; downgrade or reinstall rejected")


def decode_signature(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise UpdateValidationError("Update signature is invalid") from exc
    if len(raw) != 64:
        raise UpdateValidationError("Update signature is invalid")
    return raw
