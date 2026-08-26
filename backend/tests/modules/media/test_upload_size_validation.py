from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import settings
from app.modules.media.validation import iter_upload_chunks, validate_file_size


class _Upload:
    def __init__(self, chunks: list[bytes], *, size: int | None) -> None:
        self._chunks = list(chunks)
        self.size = size

    async def read(self, _: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_validate_file_size_uses_parsed_upload_size(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 8)
    upload = _Upload([], size=9)
    with pytest.raises(HTTPException) as exc:
        validate_file_size(upload)  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_stream_enforces_limit_when_size_metadata_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 8)
    upload = _Upload([b"1234", b"5678", b"9"], size=None)

    with pytest.raises(HTTPException) as exc:
        _ = [chunk async for chunk in iter_upload_chunks(upload)]  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_stream_accepts_exact_configured_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 8)
    upload = _Upload([b"1234", b"5678"], size=None)

    chunks = [chunk async for chunk in iter_upload_chunks(upload)]  # type: ignore[arg-type]
    assert b"".join(chunks) == b"12345678"
