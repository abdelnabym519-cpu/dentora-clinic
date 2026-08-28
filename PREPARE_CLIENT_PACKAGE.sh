#!/usr/bin/env bash
set -euo pipefail

# Build a reusable commercial client ZIP from an immutable Git revision.
# Production packaging requires the public trust roots for both licensing and Auto Update.
# Usage: PREPARE_CLIENT_PACKAGE.sh [commit-or-ref]

SOURCE_REF="${1:-HEAD}"
ROOT="$(git rev-parse --show-toplevel)"
DIST="$ROOT/dist"
OUT="$DIST/Dentora_Client"
ZIP="$DIST/Dentora_Client.zip"
SHA256="$ZIP.sha256"
LICENSE_SERVER_URL="${DENTORA_LICENSE_SERVER_URL:-}"
LICENSE_PUBLIC_KEY_B64="${DENTORA_LICENSE_PUBLIC_KEY_B64:-}"
UPDATE_METADATA_URL="${DENTORA_UPDATE_METADATA_URL:-}"
UPDATE_PUBLIC_KEY_B64="${DENTORA_UPDATE_PUBLIC_KEY_B64:-}"

echo "=== Dentora Licensed Generic Client Package ==="
echo "Source ref: $SOURCE_REF"

for required_command in git tar python; do
  command -v "$required_command" >/dev/null || {
    echo "ERROR: $required_command is required"
    exit 1
  }
done

if [[ -z "$LICENSE_SERVER_URL" || -z "$LICENSE_PUBLIC_KEY_B64" ]]; then
  echo "ERROR: Commercial package build requires pinned license trust configuration."
  echo "Set DENTORA_LICENSE_SERVER_URL and DENTORA_LICENSE_PUBLIC_KEY_B64 first."
  exit 1
fi

if [[ -z "$UPDATE_METADATA_URL" || -z "$UPDATE_PUBLIC_KEY_B64" ]]; then
  echo "ERROR: Commercial package build requires pinned Auto Update trust configuration."
  echo "Set DENTORA_UPDATE_METADATA_URL and DENTORA_UPDATE_PUBLIC_KEY_B64 first."
  exit 1
fi

SOURCE_SHA="$(git rev-parse --verify "${SOURCE_REF}^{commit}")"
echo "Source SHA: $SOURCE_SHA"

rm -rf "$OUT"
mkdir -p "$OUT"

echo "[1/6] Exporting tracked source revision..."
git archive --format=tar "$SOURCE_SHA" | tar -x -C "$OUT"

# Never distribute owner-side license services, signing material, package tooling,
# or repository/deployment internals.
rm -rf \
  "$OUT/.github" \
  "$OUT/license-server" \
  "$OUT/license-worker" \
  "$OUT/.license-dev"
rm -f \
  "$OUT/docker-compose.yml" \
  "$OUT/docker-compose.prod.yml" \
  "$OUT/.env.prod.example" \
  "$OUT/railway.frontend.toml" \
  "$OUT/backend/railway.toml" \
  "$OUT/.env.client" \
  "$OUT/PREPARE_CLIENT_PACKAGE.sh"

echo "[2/6] Pinning license and Auto Update trust configuration..."
python - \
  "$OUT/.env.client.example" \
  "$LICENSE_SERVER_URL" \
  "$LICENSE_PUBLIC_KEY_B64" \
  "$UPDATE_METADATA_URL" \
  "$UPDATE_PUBLIC_KEY_B64" <<'PY'
from __future__ import annotations

import base64
import binascii
import sys
from pathlib import Path
from urllib.parse import urlparse

path = Path(sys.argv[1])
values = {
    "LICENSE_SERVER_URL": sys.argv[2],
    "LICENSE_PUBLIC_KEY_B64": sys.argv[3],
    "UPDATE_METADATA_URL": sys.argv[4],
    "UPDATE_PUBLIC_KEY_B64": sys.argv[5],
}

for name in ("LICENSE_SERVER_URL", "UPDATE_METADATA_URL"):
    parsed = urlparse(values[name])
    if parsed.scheme != "https" or not parsed.netloc:
        raise SystemExit(f"{name} must be an absolute HTTPS URL")

for name in ("LICENSE_PUBLIC_KEY_B64", "UPDATE_PUBLIC_KEY_B64"):
    try:
        decoded = base64.b64decode(values[name], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit(f"{name} must be valid base64") from exc
    if not decoded:
        raise SystemExit(f"{name} must decode to a non-empty public key")

lines = path.read_text(encoding="utf-8").splitlines()
seen: set[str] = set()
output: list[str] = []
for line in lines:
    key, separator, _ = line.partition("=")
    if separator and key in values:
        line = f"{key}={values[key]}"
        seen.add(key)
    output.append(line)

missing = sorted(set(values) - seen)
if missing:
    raise SystemExit(f"Missing client environment keys: {', '.join(missing)}")

path.write_text("\n".join(output) + "\n", encoding="utf-8")
PY

echo "[3/6] Verifying reusable first-run configuration..."
python - "$OUT/.env.client.example" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
config = {}
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    config[key] = value

required_pinned = (
    "LICENSE_SERVER_URL",
    "LICENSE_PUBLIC_KEY_B64",
    "UPDATE_METADATA_URL",
    "UPDATE_PUBLIC_KEY_B64",
)
required_per_install = (
    "POSTGRES_PASSWORD",
    "SECRET_KEY",
    "BUDGET_PUBLIC_SECRET_KEY",
    "LICENSE_MACHINE_FINGERPRINT",
)

for key in required_pinned:
    if not config.get(key):
        raise SystemExit(f"Pinned client configuration is empty: {key}")
for key in required_per_install:
    if config.get(key):
        raise SystemExit(f"Per-install secret must remain empty in reusable package: {key}")
PY

printf '%s\n' \
  "Dentora Licensed Generic Client local production package" \
  "Source ref: $SOURCE_REF" \
  "Source SHA: $SOURCE_SHA" \
  "Reusable package: yes" \
  "Per-install secrets: generated on first start" \
  "Commercial license enforcement: enabled" \
  "License server: $LICENSE_SERVER_URL" \
  "Auto Update metadata: $UPDATE_METADATA_URL" \
  "Auto Update signature trust: pinned" \
  "Trial: disabled" \
  "Demo seed: disabled" \
  > "$OUT/BUILD_INFO.txt"

echo "[4/6] Creating ZIP..."
rm -f "$ZIP" "$SHA256"
python - "$OUT" "$ZIP" <<'PY'
from pathlib import Path
import sys
import zipfile

root = Path(sys.argv[1])
archive_path = Path(sys.argv[2])
with zipfile.ZipFile(
    archive_path,
    mode="w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=9,
) as archive:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        archive.write(path, path.relative_to(root).as_posix())
PY

echo "[5/6] Writing SHA-256 checksum..."
python - "$ZIP" "$SHA256" <<'PY'
from pathlib import Path
import hashlib
import sys

archive_path = Path(sys.argv[1])
checksum_path = Path(sys.argv[2])
digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
PY

echo "[6/6] Verifying licensed generic package..."
test -f "$OUT/docker-compose.client.yml"
test -f "$OUT/.env.client.example"
test ! -e "$OUT/.env.client"
test -f "$OUT/START_DENTORA.bat"
test -f "$OUT/UPDATE_DENTORA.bat"
test -f "$OUT/scripts/dentora_auto_update.ps1"
test -f "$OUT/CLIENT_INSTALL_AR.md"
test ! -e "$OUT/PREPARE_CLIENT_PACKAGE.sh"
test ! -e "$OUT/SET_CLIENT_PROFILE.bat"
test ! -e "$OUT/license-server"
test ! -e "$OUT/license-worker"
test ! -e "$OUT/.license-dev"
test -s "$ZIP"
test -s "$SHA256"

echo
echo "READY"
echo "Folder:   $OUT"
echo "ZIP:      $ZIP"
echo "SHA-256:  $SHA256"
echo "Source:   $SOURCE_SHA"
echo "This reusable ZIP requires a valid Dentora license key on every new installation."
