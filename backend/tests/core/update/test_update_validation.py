from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.update import UpdateValidationError, validate_update
from app.core.update.infrastructure import canonical_payload


def _fixture(tmp_path: Path, **overrides: object) -> tuple[Path, Path, str, dict[str, object]]:
    package = tmp_path / "dentora-update.zip"
    package.write_bytes(b"trusted-update-package")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    descriptor: dict[str, object] = {
        "version": "2.1.0",
        "compatible_from": "2.0.0",
        "package_url": "https://updates.example.test/dentora-2.1.0.zip",
        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "size": package.stat().st_size,
        "schema_revision": "abc123def456",
        "requires_backup": True,
    }
    descriptor.update(overrides)
    signature = private.sign(canonical_payload(descriptor))
    metadata = tmp_path / "update.json"
    metadata.write_text(
        json.dumps(
            {
                "descriptor": descriptor,
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    return metadata, package, base64.b64encode(public).decode("ascii"), descriptor


def test_valid_signed_upgrade_is_accepted(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(tmp_path)
    result = validate_update(
        metadata, package, public_key_b64=public_key, current_version="2.0.0"
    )
    assert result.version == "2.1.0"
    assert result.compatible_from == "2.0.0"
    assert result.requires_backup is True


def test_tampered_metadata_is_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(tmp_path)
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["descriptor"]["version"] = "9.9.9"
    metadata.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(UpdateValidationError, match="signature"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")


def test_corrupted_package_is_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(tmp_path)
    package.write_bytes(b"corrupted-package-bytes")
    with pytest.raises(UpdateValidationError, match="size|checksum"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")


def test_same_version_is_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(tmp_path, version="2.0.0")
    with pytest.raises(UpdateValidationError, match="strict upgrade"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")


def test_downgrade_is_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(tmp_path, version="1.9.9")
    with pytest.raises(UpdateValidationError, match="strict upgrade"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")


def test_incompatible_source_version_is_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(tmp_path, compatible_from="1.9.0")
    with pytest.raises(UpdateValidationError, match="incompatible"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")


def test_non_https_package_url_is_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, _ = _fixture(
        tmp_path, package_url="http://updates.example.test/update.zip"
    )
    with pytest.raises(UpdateValidationError, match="HTTPS"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")


def test_unknown_descriptor_fields_are_rejected(tmp_path: Path) -> None:
    metadata, package, public_key, descriptor = _fixture(tmp_path)
    descriptor["command"] = "arbitrary-command"
    private = Ed25519PrivateKey.generate()
    signature = private.sign(canonical_payload(descriptor))
    metadata.write_text(
        json.dumps(
            {
                "descriptor": descriptor,
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    public_key = base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii")
    with pytest.raises(UpdateValidationError, match="unsupported"):
        validate_update(metadata, package, public_key_b64=public_key, current_version="2.0.0")
