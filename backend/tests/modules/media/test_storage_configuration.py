from __future__ import annotations

import pytest

from app.modules.media.storage.configuration import S3StorageConfig


def _base_env(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "dentora-test")
    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)


def test_s3_endpoint_allows_http_outside_production(monkeypatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    assert S3StorageConfig.from_env().endpoint_url == "http://minio:9000"


def test_s3_endpoint_requires_https_in_production(monkeypatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("S3_ENDPOINT", "http://storage.example.test")
    with pytest.raises(ValueError, match="HTTPS"):
        S3StorageConfig.from_env()


def test_s3_endpoint_rejects_embedded_credentials(monkeypatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("S3_ENDPOINT", "https://user:secret@storage.example.test")
    with pytest.raises(ValueError, match="plain http"):
        S3StorageConfig.from_env()
