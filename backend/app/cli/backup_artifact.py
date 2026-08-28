"""CLI adapter for Dentora backup artifact creation and validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.backup import BackupValidationError, create_manifest, validate_artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dentora backup artifact validator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create and validate manifest.json")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--backup-id", required=True)
    create.add_argument("--created-at-utc", required=True)
    create.add_argument("--app-version", required=True)
    create.add_argument("--schema-revision", required=True)

    validate = subparsers.add_parser("validate", help="Validate a complete extracted backup")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--app-version", required=True)
    validate.add_argument("--schema-revision", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create":
            manifest = create_manifest(
                args.root,
                backup_id=args.backup_id,
                created_at_utc=args.created_at_utc,
                app_version=args.app_version,
                schema_revision=args.schema_revision,
            )
        else:
            manifest = validate_artifact(
                args.root,
                app_version=args.app_version,
                schema_revision=args.schema_revision,
            )
    except BackupValidationError as exc:
        print(f"INVALID: {exc}")
        return 2

    print(json.dumps({"backup_id": manifest.backup_id, "status": "valid"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
