"""Infrastructure helpers for Dentora backup artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import BackupValidationError


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupValidationError("Backup manifest cannot be read") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def validate_storage_tar(path: Path) -> None:
    try:
        with tarfile.open(path, mode="r:") as archive:
            for member in archive.getmembers():
                _validate_tar_member(member)
    except (tarfile.TarError, OSError) as exc:
        raise BackupValidationError("Storage archive is corrupted or unreadable") from exc


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    raw_name = member.name.replace("\\", "/")
    path = PurePosixPath(raw_name)
    if path.is_absolute():
        raise BackupValidationError("Storage archive contains an absolute path")
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if any(part == ".." for part in parts):
        raise BackupValidationError("Storage archive contains path traversal")
    if parts and parts[0].lower() == "license":
        raise BackupValidationError("Backup must not contain machine-bound license state")
    if member.issym() or member.islnk():
        raise BackupValidationError("Storage archive links are not supported")
    if not (member.isfile() or member.isdir()):
        raise BackupValidationError("Storage archive contains an unsupported entry type")
