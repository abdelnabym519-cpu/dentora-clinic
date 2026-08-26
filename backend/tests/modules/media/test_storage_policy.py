from __future__ import annotations

import pytest
from sqlalchemy import LargeBinary

from app.modules.media.models import Document, MediaAttachment
from app.modules.media.storage import S3StorageBackend, get_storage_backend


def test_factory_builds_s3_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    monkeypatch.setenv("S3_BUCKET", "dentora-test")
    monkeypatch.setenv("S3_ACCESS_KEY", "test")
    monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
    monkeypatch.setenv("S3_ADDRESSING_STYLE", "path")
    get_storage_backend.cache_clear()
    try:
        backend = get_storage_backend("s3")
        assert isinstance(backend, S3StorageBackend)
        assert backend.config.bucket == "dentora-test"
    finally:
        get_storage_backend.cache_clear()


def test_factory_rejects_unknown_backend() -> None:
    get_storage_backend.cache_clear()
    with pytest.raises(ValueError, match="Unknown storage backend"):
        get_storage_backend("database")


def test_media_schema_has_no_binary_payload_columns() -> None:
    for table in (Document.__table__, MediaAttachment.__table__):
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
