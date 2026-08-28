"""Domain rules for Dentora backup artifacts.

This module contains format and compatibility invariants only. It deliberately
has no filesystem, database, Docker, or operating-system dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

BACKUP_FORMAT = "dentora-backup"
BACKUP_FORMAT_VERSION = 1
REQUIRED_COMPONENT_NAMES = frozenset({"database.dump", "storage.tar"})
_ALLOWED_MANIFEST_KEYS = frozenset(
    {
        "format",
        "format_version",
        "backup_id",
        "created_at_utc",
        "app_version",
        "schema_revision",
        "storage_backend",
        "source",
        "components",
    }
)
_ALLOWED_SOURCE_KEYS = frozenset({"deployment", "database", "storage", "license_state"})
_ALLOWED_COMPONENT_KEYS = frozenset({"name", "size", "sha256"})
_BACKUP_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,96}$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
_SENSITIVE_KEY_PARTS = (
    "secret",
    "password",
    "credential",
    "token",
    "fingerprint",
    "private_key",
    "api_key",
)


class BackupValidationError(ValueError):
    """Backup metadata or artifact contents failed a fail-closed validation."""


@dataclass(frozen=True)
class ComponentDigest:
    name: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, value: Any) -> ComponentDigest:
        if not isinstance(value, dict) or set(value) != _ALLOWED_COMPONENT_KEYS:
            raise BackupValidationError("Backup component metadata is incomplete or unsupported")
        name = value.get("name")
        size = value.get("size")
        sha256 = value.get("sha256")
        if name not in REQUIRED_COMPONENT_NAMES:
            raise BackupValidationError("Backup contains an unexpected component")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise BackupValidationError(f"Backup component {name} has an invalid size")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise BackupValidationError(f"Backup component {name} has an invalid SHA-256")
        return cls(name=name, size=size, sha256=sha256)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    created_at_utc: str
    app_version: str
    schema_revision: str
    storage_backend: str
    source: dict[str, str]
    components: tuple[ComponentDigest, ...]
    format: str = BACKUP_FORMAT
    format_version: int = BACKUP_FORMAT_VERSION

    @classmethod
    def from_dict(cls, value: Any) -> BackupManifest:
        if not isinstance(value, dict) or set(value) != _ALLOWED_MANIFEST_KEYS:
            raise BackupValidationError("Backup manifest is incomplete or uses unsupported fields")
        if value.get("format") != BACKUP_FORMAT:
            raise BackupValidationError("Backup format is not supported")
        if value.get("format_version") != BACKUP_FORMAT_VERSION:
            raise BackupValidationError("Backup format version is not supported")

        backup_id = value.get("backup_id")
        created_at = value.get("created_at_utc")
        app_version = value.get("app_version")
        schema_revision = value.get("schema_revision")
        storage_backend = value.get("storage_backend")
        source = value.get("source")
        raw_components = value.get("components")

        if not isinstance(backup_id, str) or not _BACKUP_ID_RE.fullmatch(backup_id):
            raise BackupValidationError("Backup identifier is invalid")
        _validate_utc_timestamp(created_at)
        if not isinstance(app_version, str) or not _VERSION_RE.fullmatch(app_version):
            raise BackupValidationError("Backup application version is invalid")
        if not isinstance(schema_revision, str) or not _SCHEMA_RE.fullmatch(schema_revision):
            raise BackupValidationError("Backup schema revision is invalid")
        if storage_backend != "local":
            raise BackupValidationError("Backup storage backend is not supported")
        if not isinstance(source, dict) or set(source) != _ALLOWED_SOURCE_KEYS:
            raise BackupValidationError("Backup source metadata is incomplete or unsupported")
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in source.items()):
            raise BackupValidationError("Backup source metadata must contain strings only")
        _reject_sensitive_metadata_keys(source)
        if source != {
            "deployment": "dentora-client",
            "database": "postgresql",
            "storage": "local",
            "license_state": "preserved-by-installation",
        }:
            raise BackupValidationError("Backup source metadata is incompatible")

        if not isinstance(raw_components, list) or len(raw_components) != len(
            REQUIRED_COMPONENT_NAMES
        ):
            raise BackupValidationError("Backup components are incomplete")
        components = tuple(ComponentDigest.from_dict(item) for item in raw_components)
        names = [component.name for component in components]
        if len(set(names)) != len(names) or set(names) != REQUIRED_COMPONENT_NAMES:
            raise BackupValidationError("Backup components are duplicated or incomplete")

        return cls(
            backup_id=backup_id,
            created_at_utc=created_at,
            app_version=app_version,
            schema_revision=schema_revision,
            storage_backend=storage_backend,
            source=dict(source),
            components=components,
        )

    def assert_compatible(self, *, app_version: str, schema_revision: str) -> None:
        if self.app_version != app_version:
            raise BackupValidationError(
                f"Backup application version {self.app_version} is incompatible with {app_version}"
            )
        if self.schema_revision != schema_revision:
            raise BackupValidationError(
                "Backup database schema is incompatible with the installed Dentora schema"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "format_version": self.format_version,
            "backup_id": self.backup_id,
            "created_at_utc": self.created_at_utc,
            "app_version": self.app_version,
            "schema_revision": self.schema_revision,
            "storage_backend": self.storage_backend,
            "source": dict(self.source),
            "components": [component.to_dict() for component in self.components],
        }


def _validate_utc_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise BackupValidationError("Backup creation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupValidationError("Backup creation timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise BackupValidationError("Backup creation timestamp must be UTC")


def _reject_sensitive_metadata_keys(value: dict[str, str]) -> None:
    for key in value:
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            raise BackupValidationError("Backup metadata must not contain secrets or credentials")
