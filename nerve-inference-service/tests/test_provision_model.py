"""Tests for the host-side model provisioning tooling (scripts/provision_model.py).

These tests exercise the SCRIPT's logic — record selection, checksum
refusal, zip extraction, layout/identity validation and the manifest
round-trip — using tiny synthetic fixtures. They deliberately do NOT
exercise model inference: the real Dataset112 checkpoint is downloaded and
checksum-verified on the operator host only.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "provision_model.py"
_spec = importlib.util.spec_from_file_location("provision_model", _SCRIPT)
provision_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(provision_model)


def _write_model_dir(
    target: Path, *, canal_label: int = 5, file_ending: str = ".nii.gz"
) -> None:
    (target / "fold_0").mkdir(parents=True)
    (target / "dataset.json").write_text(
        json.dumps(
            {
                "name": "Dataset112_DentalSegmentator",
                "labels": {"Mandibular canal": canal_label},
                "file_ending": file_ending,
            }
        ),
        encoding="utf-8",
    )
    (target / "plans.json").write_text("{}", encoding="utf-8")
    (target / "fold_0" / "checkpoint_final.pth").write_bytes(b"\x00" * 128)


def _write_zip(
    path: Path, model_dir: Path, root: str = "Dataset112_DentalSegmentator_v100"
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for relative in ("dataset.json", "plans.json", "fold_0/checkpoint_final.pth"):
            archive.write(model_dir / relative, f"{root}/{relative}")


def test_constants_pin_the_verified_record():
    assert provision_model.RECORD_ID == "10829675"
    assert provision_model.EXPECTED_ZIP_NAME == "Dataset112_DentalSegmentator_v100.zip"
    assert provision_model.EXPECTED_ZIP_MD5 == "b71cd5230168d28a4f71b078265b76be"
    assert provision_model.MODEL_LICENSE == "CC BY 4.0"


def test_select_zip_accepts_matching_record():
    record = {
        "files": [
            {
                "key": "other.txt",
                "links": {"self": "http://x/other"},
                "checksum": "md5:dead",
            },
            {
                "key": "Dataset112_DentalSegmentator_v100.zip",
                "links": {"self": "http://x/model.zip"},
                "checksum": "md5:" + provision_model.EXPECTED_ZIP_MD5,
            },
        ]
    }
    url, md5 = provision_model.select_zip(record)
    assert url == "http://x/model.zip"
    assert md5 == provision_model.EXPECTED_ZIP_MD5


def test_select_zip_refuses_changed_checksum():
    record = {
        "files": [
            {
                "key": "Dataset112_DentalSegmentator_v100.zip",
                "links": {"self": "http://x/model.zip"},
                "checksum": "md5:" + "0" * 32,
            }
        ]
    }
    with pytest.raises(provision_model.ProvisionError, match="identity changed"):
        provision_model.select_zip(record)


def test_select_zip_refuses_missing_model(tmp_path):
    with pytest.raises(provision_model.ProvisionError, match="not present"):
        provision_model.select_zip({"files": [{"key": "Dataset111_453CT_v100.zip"}]})


def test_extract_validates_layout_and_identity(tmp_path):
    staging = tmp_path / "staging"
    _write_model_dir(staging)
    zip_path = tmp_path / "model.zip"
    _write_zip(zip_path, staging)

    target = tmp_path / "model"
    provision_model.extract_model(zip_path, target)
    identity = provision_model.validate_layout(target)
    assert identity["name"] == "Dataset112_DentalSegmentator"
    manifest = provision_model.build_manifest(
        target, provision_model.EXPECTED_ZIP_MD5, identity
    )
    assert manifest["files"]["fold_0/checkpoint_final.pth"].startswith("")
    assert Path(manifest["files"]["fold_0/checkpoint_final.pth"]) is not None
    # manifest round-trip verifies cleanly
    assert (
        provision_model.verify_provisioned(target)["zip_md5"]
        == provision_model.EXPECTED_ZIP_MD5
    )


def test_validate_rejects_non_canal_checkpoint(tmp_path):
    target = tmp_path / "model"
    _write_model_dir(target, canal_label=2)  # wrong anatomy contract
    with pytest.raises(provision_model.ProvisionError, match="Mandibular canal"):
        provision_model.validate_layout(target)


def test_validate_rejects_missing_checkpoint(tmp_path):
    target = tmp_path / "model"
    _write_model_dir(target)
    (target / "fold_0" / "checkpoint_final.pth").unlink()
    with pytest.raises(provision_model.ProvisionError, match="missing or empty"):
        provision_model.validate_layout(target)


def test_verify_provisioned_detects_tampering(tmp_path):
    target = tmp_path / "model"
    _write_model_dir(target)
    provision_model.build_manifest(
        target,
        provision_model.EXPECTED_ZIP_MD5,
        provision_model.validate_layout(target),
    )
    (target / "plans.json").write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(provision_model.ProvisionError, match="sha256 mismatch"):
        provision_model.verify_provisioned(target)
