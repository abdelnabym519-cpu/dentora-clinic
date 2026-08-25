"""Regression tests for bounded Dental 3D binary ingestion reads."""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import UploadFile

from app.config import settings
from app.modules.dental_3d.cbct import DicomIngestionError, DicomIngestionErrorCode
from app.modules.dental_3d.meshfiles import MeshUploadError
from app.modules.dental_3d.router import _read_dicom_upload, _read_mesh_upload


@pytest.mark.asyncio
async def test_mesh_reader_enforces_configured_limit_without_declared_size(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 4)
    upload = UploadFile(filename="scan.stl", file=BytesIO(b"12345"))

    with pytest.raises(MeshUploadError) as exc:
        await _read_mesh_upload(upload)

    assert str(exc.value).startswith("too_large")


@pytest.mark.asyncio
async def test_dicom_reader_enforces_configured_limit_without_declared_size(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 4)
    upload = UploadFile(filename="scan.dcm", file=BytesIO(b"12345"))

    with pytest.raises(DicomIngestionError) as exc:
        await _read_dicom_upload(upload)

    assert exc.value.code is DicomIngestionErrorCode.TOO_LARGE


@pytest.mark.asyncio
async def test_bounded_readers_preserve_valid_payload(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 16)
    payload = b"dentora"

    mesh = UploadFile(filename="scan.stl", file=BytesIO(payload))
    dicom = UploadFile(filename="scan.dcm", file=BytesIO(payload))

    assert await _read_mesh_upload(mesh) == payload
    assert await _read_dicom_upload(dicom) == payload
