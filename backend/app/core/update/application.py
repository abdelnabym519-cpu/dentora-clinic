"""Application service for validating a Dentora update before mutation."""

from __future__ import annotations

import json
from pathlib import Path

from .domain import UpdateDescriptor, UpdateValidationError
from .infrastructure import verify_package, verify_signed_descriptor


def validate_update(
    metadata_path: Path,
    package_path: Path,
    *,
    public_key_b64: str,
    current_version: str,
) -> UpdateDescriptor:
    try:
        envelope = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateValidationError("Update metadata cannot be read") from exc
    descriptor = verify_signed_descriptor(envelope, public_key_b64=public_key_b64)
    descriptor.assert_upgrade_from(current_version)
    verify_package(package_path, descriptor)
    return descriptor
