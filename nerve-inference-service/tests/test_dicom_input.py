from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

from app.dicom_input import InputArchiveError, prepare_dicom_archive


def _archive(*, extra_name: str | None = None) -> bytes:
    manifest = {
        "contract": "dentora-nerve-input-v1",
        "study_instance_uid": "1.2.3",
        "series_instance_uid": "1.2.3.4",
        "frame_of_reference_uid": "1.2.3.5",
        "instance_count": 1,
        "instances": [{"file": "0000.dcm"}],
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("0000.dcm", b"not-needed-for-structural-rejection-tests")
        if extra_name:
            archive.writestr(extra_name, b"unexpected")
    return buffer.getvalue()


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_digest_mismatch_fails_before_dicom_parsing(tmp_path: Path) -> None:
    payload = _archive()
    with pytest.raises(InputArchiveError, match="digest"):
        prepare_dicom_archive(
            payload,
            expected_digest="sha256:" + "0" * 64,
            destination=tmp_path,
            max_request_bytes=1024 * 1024,
        )


def test_unexpected_archive_name_is_rejected_before_extraction(tmp_path: Path) -> None:
    payload = _archive(extra_name="../escape.dcm")
    with pytest.raises(InputArchiveError, match="unexpected file name"):
        prepare_dicom_archive(
            payload,
            expected_digest=_digest(payload),
            destination=tmp_path,
            max_request_bytes=1024 * 1024,
        )
    assert list(tmp_path.iterdir()) == []
