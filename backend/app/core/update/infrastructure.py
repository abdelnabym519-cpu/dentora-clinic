"""Infrastructure verification for Dentora update artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .domain import UpdateDescriptor, UpdateValidationError, decode_signature


def canonical_payload(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def verify_signed_descriptor(envelope: Any, *, public_key_b64: str) -> UpdateDescriptor:
    if not isinstance(envelope, dict) or set(envelope) != {"descriptor", "signature"}:
        raise UpdateValidationError("Update metadata envelope is invalid")
    descriptor = envelope.get("descriptor")
    signature = envelope.get("signature")
    if not isinstance(descriptor, dict) or not isinstance(signature, str):
        raise UpdateValidationError("Update metadata envelope is invalid")
    try:
        key_bytes = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        raise UpdateValidationError("Update public key is invalid") from exc
    if len(key_bytes) != 32:
        raise UpdateValidationError("Update public key is invalid")
    try:
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(
            decode_signature(signature), canonical_payload(descriptor)
        )
    except InvalidSignature as exc:
        raise UpdateValidationError("Update metadata signature verification failed") from exc
    return UpdateDescriptor.from_dict(descriptor)


def verify_package(path: Path, descriptor: UpdateDescriptor) -> None:
    if not path.is_file() or path.is_symlink():
        raise UpdateValidationError("Update package is missing")
    if path.stat().st_size != descriptor.size:
        raise UpdateValidationError("Update package size does not match signed metadata")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != descriptor.sha256:
        raise UpdateValidationError("Update package checksum does not match signed metadata")
