from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

_DICOM_NAME = re.compile(r"^[0-9]{4}\.dcm$")
_FORBIDDEN_IDENTITY_TAGS = ("PatientName", "PatientID", "PatientBirthDate", "PatientAddress")


class InputArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedInput:
    files: tuple[Path, ...]
    study_instance_uid: str
    series_instance_uid: str
    frame_of_reference_uid: str


def _validate_digest(payload: bytes, expected_digest: str) -> None:
    actual = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if expected_digest != actual:
        raise InputArchiveError("input digest does not match request body")


def prepare_dicom_archive(
    payload: bytes,
    *,
    expected_digest: str,
    destination: Path,
    max_request_bytes: int,
) -> PreparedInput:
    if not payload or len(payload) > max_request_bytes:
        raise InputArchiveError("input archive is empty or exceeds the configured size limit")
    _validate_digest(payload, expected_digest)
    try:
        archive = ZipFile(BytesIO(payload), "r")
    except BadZipFile as exc:
        raise InputArchiveError("input is not a valid ZIP archive") from exc

    with archive:
        names = archive.namelist()
        if not names or names[0] != "manifest.json" or names.count("manifest.json") != 1:
            raise InputArchiveError("archive must contain one manifest.json as its first entry")
        if len(names) > 513:
            raise InputArchiveError("archive contains too many entries")
        if len(set(names)) != len(names):
            raise InputArchiveError("archive contains duplicate entries")
        if any(name != "manifest.json" and not _DICOM_NAME.fullmatch(name) for name in names):
            raise InputArchiveError("archive contains an unexpected file name")
        if sum(info.file_size for info in archive.infolist()) > max_request_bytes:
            raise InputArchiveError("expanded archive exceeds the configured size limit")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as exc:
            raise InputArchiveError("manifest.json is invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("contract") != "dentora-nerve-input-v1":
            raise InputArchiveError("input manifest contract is invalid")
        instances = manifest.get("instances")
        if not isinstance(instances, list) or not instances:
            raise InputArchiveError("input manifest has no instances")
        if manifest.get("instance_count") != len(instances):
            raise InputArchiveError("input manifest instance count is inconsistent")
        listed = [item.get("file") if isinstance(item, dict) else None for item in instances]
        if any(not isinstance(name, str) or not _DICOM_NAME.fullmatch(name) for name in listed):
            raise InputArchiveError("input manifest contains an invalid DICOM file name")
        if len(set(listed)) != len(listed) or set(listed) != set(names[1:]):
            raise InputArchiveError("archive DICOM files do not match the manifest")

        study_uid = manifest.get("study_instance_uid")
        series_uid = manifest.get("series_instance_uid")
        frame_uid = manifest.get("frame_of_reference_uid")
        if not all(isinstance(value, str) and value for value in (study_uid, series_uid, frame_uid)):
            raise InputArchiveError("manifest is missing DICOM reference UIDs")

        destination.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        try:
            from pydicom import dcmread
            from pydicom.errors import InvalidDicomError
        except ImportError as exc:  # pragma: no cover - runtime image always includes pydicom
            raise RuntimeError("pydicom is required by the inference service") from exc

        for name in listed:
            raw = archive.read(name)
            try:
                dataset = dcmread(BytesIO(raw), force=False)
            except (InvalidDicomError, EOFError, OSError, ValueError) as exc:
                raise InputArchiveError("archive contains an invalid DICOM instance") from exc
            if str(getattr(dataset, "Modality", "")).upper() != "CT" or "PixelData" not in dataset:
                raise InputArchiveError("only CT DICOM instances with pixel data are accepted")
            if any(keyword in dataset for keyword in _FORBIDDEN_IDENTITY_TAGS):
                raise InputArchiveError("input DICOM contains a forbidden identity tag")
            if any(element.tag.is_private for element in dataset.iterall()):
                raise InputArchiveError("input DICOM contains a private tag")
            if (
                str(getattr(dataset, "StudyInstanceUID", "")) != study_uid
                or str(getattr(dataset, "SeriesInstanceUID", "")) != series_uid
                or str(getattr(dataset, "FrameOfReferenceUID", "")) != frame_uid
            ):
                raise InputArchiveError("DICOM reference UIDs do not match the manifest")
            target = destination / name
            target.write_bytes(raw)
            paths.append(target)

    return PreparedInput(
        files=tuple(paths),
        study_instance_uid=study_uid,
        series_instance_uid=series_uid,
        frame_of_reference_uid=frame_uid,
    )
