"""CLI used by the Windows updater to validate signed release metadata and package bytes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.update import UpdateValidationError, validate_update


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--public-key-b64", required=True)
    parser.add_argument("--current-version", required=True)
    args = parser.parse_args()
    try:
        descriptor = validate_update(
            Path(args.metadata),
            Path(args.package),
            public_key_b64=args.public_key_b64,
            current_version=args.current_version,
        )
    except UpdateValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(descriptor.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
