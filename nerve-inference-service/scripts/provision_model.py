#!/usr/bin/env python3
"""Provision the REAL DentalSegmentator mandibular-canal checkpoint (host-side).

Dentora's nerve service requires the trained nnU-Net v2 checkpoint

    Dataset112_DentalSegmentator_v100  (Zenodo record 10829675,
    DOI 10.5281/zenodo.10829674, file Dataset112_DentalSegmentator_v100.zip,
    recorded md5 b71cd5230168d28a4f71b078265b76be)

laid out as:

    <target>/
      dataset.json
      plans.json
      fold_0/checkpoint_final.pth

Weights are CC BY 4.0 (verified against the Zenodo record metadata and
multiple independent integration audits) — commercial use is permitted with
attribution (Dot G, et al. DentalSegmentator: robust open source deep
learning-based CT and CBCT image segmentation. J Dentistry 2024,
doi:10.1016/j.jdent.2024.105130). They are never committed to this
repository; this script downloads, checksum-verifies, extracts, validates
and manifests them on the operator host.

Idempotent: if the target already contains a valid model + manifest, the
download is skipped (pass --force to re-provision).

Usage (on the host, not inside Arena):

    python nerve-inference-service/scripts/provision_model.py \
        --target "C:/Dentora/Models/DentalSegmentator"
    python nerve-inference-service/scripts/provision_model.py --target ... --force
    python nerve-inference-service/scripts/provision_model.py --verify-only --target ...

Exit codes: 0 = provisioned/verified, 1 = checksum/validation failure,
2 = network/record error, 3 = invalid arguments.

WARNING: do NOT substitute the GitHub release asset
``Dataset111_453CT_v100.zip`` — that is the earlier teeth-only model and the
service's runtime contract (dataset.json label ``Mandibular canal`` == 5)
will refuse it. Only the Zenodo Dataset112 checkpoint serves the canal task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

RECORD_ID = "10829675"
RECORD_DOI = "10.5281/zenodo.10829675"
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
EXPECTED_ZIP_NAME = "Dataset112_DentalSegmentator_v100.zip"
# Recorded from the Zenodo record metadata by independent integrations that
# downloaded this exact file; re-confirmed against the record API at runtime.
EXPECTED_ZIP_MD5 = "b71cd5230168d28a4f71b078265b76be"
REQUIRED_FILES = (
    Path("dataset.json"),
    Path("plans.json"),
    Path("fold_0") / "checkpoint_final.pth",
)
MODEL_LICENSE = "CC BY 4.0"
ATTRIBUTION = (
    "Dot G, et al. DentalSegmentator: robust open source deep learning-based "
    "CT and CBCT image segmentation. Journal of Dentistry (2024). "
    "doi:10.1016/j.jdent.2024.105130"
)
MANIFEST_NAME = "model_manifest.json"


class ProvisionError(RuntimeError):
    pass


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_record() -> dict:
    """Return the Zenodo record metadata (files + declared checksums)."""
    try:
        with urllib.request.urlopen(RECORD_API, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network, DNS, HTTP errors all end here
        raise ProvisionError(
            f"cannot reach Zenodo record {RECORD_ID} ({exc}). Download "
            f"{EXPECTED_ZIP_NAME} manually from "
            f"https://zenodo.org/records/{RECORD_ID} and pass it via --zip."
        ) from exc


def select_zip(record: dict) -> tuple[str, str]:
    """Pick the Dataset112 zip from the record; return (url, md5)."""
    for entry in record.get("files", []):
        key = entry.get("key", "")
        if key.lower() == EXPECTED_ZIP_NAME.lower():
            metadata = entry.get("checksum") or ""
            recorded = metadata.split(":", 1)[-1].strip().lower()
            if recorded and recorded != EXPECTED_ZIP_MD5:
                raise ProvisionError(
                    f"Zenodo now lists md5 {recorded} for {key} but the "
                    f"recorded provenance md5 is {EXPECTED_ZIP_MD5}; refusing "
                    "to provision an artifact whose identity changed."
                )
            return str(entry["links"]["self"]), recorded or EXPECTED_ZIP_MD5
    raise ProvisionError(
        f"{EXPECTED_ZIP_NAME} is not present in Zenodo record {RECORD_ID}; "
        f"found: {[entry.get('key') for entry in record.get('files', [])]}"
    )


def download(url: str, destination: Path) -> None:
    with (
        urllib.request.urlopen(url, timeout=300) as response,
        destination.open("wb") as handle,
    ):
        shutil.copyfileobj(response, handle)


def extract_model(zip_path: Path, target: Path) -> None:
    """Extract dataset.json/plans.json/fold_0 from the zip into ``target``."""
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        wanted = {}
        for name in names:
            parts = name.split("/")
            if (
                len(parts) >= 2
                and parts[-2] == "fold_0"
                and parts[-1] == "checkpoint_final.pth"
            ):
                wanted["fold_0/checkpoint_final.pth"] = name
            elif parts[-1] in {"dataset.json", "plans.json"}:
                # prefer the shallowest occurrence (zip may nest one folder)
                existing = wanted.get(parts[-1])
                depth = len(parts)
                if existing is None or depth < len(existing.split("/")):
                    wanted[parts[-1]] = name
        missing = {"dataset.json", "plans.json", "fold_0/checkpoint_final.pth"} - set(
            wanted
        )
        if missing:
            raise ProvisionError(
                f"checkpoint zip does not contain the expected layout; missing {sorted(missing)}"
            )
        target.mkdir(parents=True, exist_ok=True)
        for relative, archive_name in wanted.items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(archive_name) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def validate_layout(target: Path) -> dict:
    """Structural + identity validation mirroring the service runtime."""
    problems: list[str] = []
    for relative in REQUIRED_FILES:
        path = target / relative
        if not path.is_file() or path.stat().st_size == 0:
            problems.append(f"missing or empty: {relative}")
    dataset_path = target / "dataset.json"
    identity: dict = {}
    if dataset_path.is_file():
        try:
            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"dataset.json does not parse: {exc}")
        else:
            identity = {
                "name": dataset.get("name") or dataset.get("dataset_name"),
                "labels": dataset.get("labels"),
                "file_ending": dataset.get("file_ending"),
            }
            if (dataset.get("labels") or {}).get("Mandibular canal") != 5:
                problems.append(
                    'dataset.json labels do not contain "Mandibular canal": 5 '
                    "— this is not the canal-capable Dataset112 checkpoint"
                )
            if dataset.get("file_ending") != ".nii.gz":
                problems.append(
                    f"dataset.json file_ending is {dataset.get('file_ending')!r}, expected '.nii.gz'"
                )
    if problems:
        raise ProvisionError("; ".join(problems))
    return identity


def build_manifest(target: Path, zip_md5: str, identity: dict) -> dict:
    manifest = {
        "model": "DentalSegmentator",
        "dataset": "Dataset112_DentalSegmentator_v100",
        "record_id": RECORD_ID,
        "doi": RECORD_DOI,
        "zip_name": EXPECTED_ZIP_NAME,
        "zip_md5": zip_md5,
        "files": {
            str(relative): _sha256(target / relative) for relative in REQUIRED_FILES
        },
        "license": MODEL_LICENSE,
        "attribution": ATTRIBUTION,
        "identity": identity,
        "provisioned_at": datetime.now(UTC).isoformat(),
    }
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def verify_provisioned(target: Path) -> dict:
    """Re-verify an existing provisioned model against its manifest."""
    manifest_path = target / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ProvisionError(
            f"{manifest_path} not found — run without --verify-only first"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_layout(target)
    for relative, recorded in manifest.get("files", {}).items():
        actual = _sha256(target / relative)
        if actual != recorded:
            raise ProvisionError(
                f"sha256 mismatch for {relative}: recorded {recorded}, actual {actual}"
            )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--target", type=Path, help="model directory to provision")
    parser.add_argument(
        "--zip", type=Path, help="use a manually downloaded zip instead of downloading"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download even if already provisioned"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="only re-verify an existing provisioning",
    )
    args = parser.parse_args()
    if args.verify_only and not args.target:
        parser.error("--verify-only requires --target")

    target = args.target
    try:
        if args.verify_only:
            manifest = verify_provisioned(target)
            print(
                f"VERIFIED {target} (md5 {manifest['zip_md5']}, license {manifest['license']})"
            )
            return 0

        if target is None:
            parser.error("--target is required")
        if not args.force and (target / MANIFEST_NAME).is_file():
            manifest = verify_provisioned(target)
            print(
                f"Already provisioned and verified: {target} (use --force to re-provision)"
            )
            print(f"  zip md5: {manifest['zip_md5']}")
            return 0

        if args.zip is not None:
            zip_path = args.zip
            actual = _md5(zip_path)
            if actual != EXPECTED_ZIP_MD5:
                raise ProvisionError(
                    f"manual zip md5 {actual} does not match the recorded provenance "
                    f"md5 {EXPECTED_ZIP_MD5} — refusing to provision"
                )
            zip_md5 = actual
        else:
            print(f"Querying Zenodo record {RECORD_ID} ...")
            url, recorded_md5 = select_zip(fetch_record())
            with tempfile.TemporaryDirectory(prefix="dentora-nerve-provision-") as tmp:
                zip_path = Path(tmp) / EXPECTED_ZIP_NAME
                print(f"Downloading {EXPECTED_ZIP_NAME} (~230 MB) ...")
                download(url, zip_path)
                actual = _md5(zip_path)
                if actual != recorded_md5 or actual != EXPECTED_ZIP_MD5:
                    raise ProvisionError(
                        f"downloaded zip md5 {actual} does not match the recorded "
                        f"md5 {EXPECTED_ZIP_MD5} — refusing to provision"
                    )
                zip_md5 = actual
                print(f"md5 verified: {zip_md5}")
                shutil.rmtree(target, ignore_errors=True)
                extract_model(zip_path, target)

        print("Validating layout + model identity ...")
        identity = validate_layout(target)
        manifest = build_manifest(target, zip_md5, identity)
        print(f"Provisioned: {target}")
        print(f"  files sha256: {json.dumps(manifest['files'], indent=2)}")
        print(f"  license: {MODEL_LICENSE} (commercial use permitted with attribution)")
        print(f"  attribution: {ATTRIBUTION}")
        print(
            "\nNext steps:\n"
            f"  1. export DENTORA_NERVE_MODEL_HOST_DIR={target}\n"
            "  2. docker compose -f docker-compose.yml -f docker-compose.nerve-ai.yml up -d nerve-inference\n"
            "  3. production additionally requires DENTORA_NERVE_COMMERCIAL_USE_APPROVED=true\n"
            "  4. python nerve-inference-service/scripts/verify_model_dir.py --env\n"
        )
        return 0
    except ProvisionError as exc:
        print(f"PROVISION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
