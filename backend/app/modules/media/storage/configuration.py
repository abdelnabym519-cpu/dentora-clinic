"""Environment-driven S3-compatible storage configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

_MIN_S3_PART_SIZE = 5 * 1024 * 1024


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _validated_endpoint() -> str | None:
    endpoint = _optional("S3_ENDPOINT")
    if endpoint is None:
        return None
    parsed = urlsplit(endpoint)
    invalid = (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    )
    if invalid:
        raise ValueError("S3_ENDPOINT must be a plain http(s) service URL")
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    if environment == "production" and parsed.scheme != "https":
        raise ValueError("S3_ENDPOINT must use HTTPS in production")
    return endpoint


@dataclass(frozen=True, slots=True)
class S3StorageConfig:
    """Configuration accepted by AWS S3, MinIO and S3-compatible providers."""

    endpoint_url: str | None
    region_name: str
    bucket: str
    access_key: str | None
    secret_key: str | None
    prefix: str
    presign_expiry_seconds: int
    multipart_threshold_bytes: int
    multipart_part_size_bytes: int
    addressing_style: str

    @classmethod
    def from_env(cls) -> S3StorageConfig:
        """Load configuration without ever embedding credentials in source."""
        bucket = os.getenv("S3_BUCKET", "").strip()
        if not bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")

        access_key = _optional("S3_ACCESS_KEY")
        secret_key = _optional("S3_SECRET_KEY")
        if bool(access_key) != bool(secret_key):
            raise ValueError("S3_ACCESS_KEY and S3_SECRET_KEY must be configured together")

        part_size = _positive_int("S3_MULTIPART_PART_SIZE_BYTES", 8 * 1024 * 1024)
        if part_size < _MIN_S3_PART_SIZE:
            raise ValueError("S3_MULTIPART_PART_SIZE_BYTES must be at least 5 MiB")
        threshold = _positive_int("S3_MULTIPART_THRESHOLD_BYTES", 8 * 1024 * 1024)
        if threshold < part_size:
            threshold = part_size

        expiry = _positive_int("S3_PRESIGN_EXPIRY_SECONDS", 900)
        if expiry > 7 * 24 * 60 * 60:
            raise ValueError("S3_PRESIGN_EXPIRY_SECONDS cannot exceed 7 days")

        addressing_style = os.getenv("S3_ADDRESSING_STYLE", "auto").strip().lower() or "auto"
        if addressing_style not in {"auto", "path", "virtual"}:
            raise ValueError("S3_ADDRESSING_STYLE must be auto, path, or virtual")

        prefix = os.getenv("S3_PREFIX", "dentora").strip().strip("/")
        if ".." in prefix.split("/") or "\\" in prefix:
            raise ValueError("S3_PREFIX contains an unsafe path component")

        return cls(
            endpoint_url=_validated_endpoint(),
            region_name=os.getenv("S3_REGION", "us-east-1").strip() or "us-east-1",
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            prefix=prefix,
            presign_expiry_seconds=expiry,
            multipart_threshold_bytes=threshold,
            multipart_part_size_bytes=part_size,
            addressing_style=addressing_style,
        )
