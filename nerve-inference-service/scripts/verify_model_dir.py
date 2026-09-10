#!/usr/bin/env python3
"""Verify a DentalSegmentator/nnU-Net model directory for the nerve service.

The CBCT nerve-inference service loads (read-only):

    <DENTORA_NERVE_MODEL_HOST_DIR>/
      dataset.json
      plans.json
      fold_0/checkpoint_final.pth

Weights are external artifacts (DentalSegmentator Dataset112,
``Dataset112_DentalSegmentator_v100.zip``, Zenodo record 10829675,
DOI 10.5281/zenodo.10829675, recorded zip md5
``b71cd5230168d28a4f71b078265b76be``). The trained weights are licensed
**CC BY 4.0** (verified against the Zenodo record metadata and independent
integration audits) — commercial use is permitted with attribution; see
``docs/technical/dental_3d/patient_registration.md`` and the service README.
They are never committed to this repository; the operator provisions them
(``scripts/provision_model.py`` automates download + checksum + layout) and
this script validates the layout **before** `docker compose -f
docker-compose.nerve-ai.yml up` fails at health-check time.

Usage (on the host):

    python nerve-inference-service/scripts/verify_model_dir.py /path/to/model
    python nerve-inference-service/scripts/verify_model_dir.py --env  # read DENTORA_NERVE_MODEL_HOST_DIR

Exit codes: 0 = valid, 1 = invalid layout, 2 = missing path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REQUIRED_FILES = (
    Path("dataset.json"),
    Path("plans.json"),
    Path("fold_0") / "checkpoint_final.pth",
)


def check(model_dir: Path) -> int:
    if not model_dir.is_dir():
        print(f"MISSING: {model_dir} is not a directory")
        return 2

    ok = True
    for relative in REQUIRED_FILES:
        target = model_dir / relative
        if target.is_file() and target.stat().st_size > 0:
            print(f"  OK       {relative}  ({target.stat().st_size / 1e6:.1f} MB)")
        else:
            print(f"  MISSING  {relative}")
            ok = False

    dataset = model_dir / "dataset.json"
    if dataset.is_file():
        try:
            payload = json.loads(dataset.read_text())
            name = payload.get("name") or payload.get("dataset_name")
            labels = payload.get("labels") or payload.get("channel_names")
            print(f"  dataset.json parses (name={name!r})")
            if labels:
                keys = list(labels) if isinstance(labels, dict) else labels
                print(f"  labels/keys: {keys}")
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  INVALID  dataset.json does not parse: {exc}")
            ok = False

    if ok:
        print(
            "\nModel dir is structurally valid. Provision with:\n"
            f"  export DENTORA_NERVE_MODEL_HOST_DIR={model_dir}\n"
            "  docker compose -f docker-compose.yml -f docker-compose.nerve-ai.yml up -d nerve-inference\n"
            "\nRemember: production inference additionally requires\n"
            "DENTORA_NERVE_COMMERCIAL_USE_APPROVED=true (operational guard —\n"
            "review the licensing notes in nerve-inference-service/README.md)."
        )
        return 0
    print("\nINVALID: the service will report missing_model until the layout matches.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("model_dir", nargs="?", type=Path)
    parser.add_argument("--env", action="store_true", help="read DENTORA_NERVE_MODEL_HOST_DIR")
    args = parser.parse_args()

    model_dir = args.model_dir
    if args.env or model_dir is None:
        value = os.environ.get("DENTORA_NERVE_MODEL_HOST_DIR")
        if not value:
            parser.error("pass a model dir or set DENTORA_NERVE_MODEL_HOST_DIR")
        model_dir = Path(value)
    return check(model_dir)


if __name__ == "__main__":
    sys.exit(main())
