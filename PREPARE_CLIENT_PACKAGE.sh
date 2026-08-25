#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-feature/license-activation}"
ROOT="$(git rev-parse --show-toplevel)"
DIST="$ROOT/dist"
OUT="$DIST/Dentora_Client"
ZIP="$DIST/Dentora_Client.zip"
LICENSE_SERVER_URL="${DENTORA_LICENSE_SERVER_URL:-}"
LICENSE_PUBLIC_KEY_B64="${DENTORA_LICENSE_PUBLIC_KEY_B64:-}"
# A distributable client must start from an immutable, published release. The
# release workflow attaches this manifest and its SHA-256 checksum.
RELEASE_VERSION="${DENTORA_RELEASE_VERSION:-}"
RELEASE_REPOSITORY="${DENTORA_RELEASE_REPOSITORY:-abdelnabym519-cpu/dentora-clinic}"

echo "=== Dentora Licensed Generic Client Package ==="
echo "Source branch: $BRANCH"

command -v git >/dev/null || { echo "git is required"; exit 1; }

if [[ -z "$LICENSE_SERVER_URL" || -z "$LICENSE_PUBLIC_KEY_B64" ]]; then
  echo "ERROR: Commercial package build requires the pinned license service configuration."
  echo "Set DENTORA_LICENSE_SERVER_URL and DENTORA_LICENSE_PUBLIC_KEY_B64 first."
  exit 1
fi
if [[ ! "$RELEASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: Set DENTORA_RELEASE_VERSION to a published semantic version, e.g. 2.0.1."
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"

echo "[1/5] Exporting tracked generic client branch..."
git archive --format=tar "$BRANCH" | tar -x -C "$OUT"

# Never distribute owner-side license services, signing material, or repository/deployment internals.
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
  "$OUT/.env.client"

echo "[2/5] Pinning commercial activation service..."
python - "$OUT/.env.client.example" "$LICENSE_SERVER_URL" "$LICENSE_PUBLIC_KEY_B64" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
server_url = sys.argv[2]
public_key_b64 = sys.argv[3]
text = path.read_text(encoding="utf-8")
lines = []
for line in text.splitlines():
    if line.startswith("LICENSE_SERVER_URL="):
        line = f"LICENSE_SERVER_URL={server_url}"
    elif line.startswith("LICENSE_PUBLIC_KEY_B64="):
        line = f"LICENSE_PUBLIC_KEY_B64={public_key_b64}"
    lines.append(line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

echo "[3/5] Pinning the client to the published immutable release..."
test -f "$OUT/.env.client.example"
RELEASE_BASE="https://github.com/${RELEASE_REPOSITORY}/releases/download/v${RELEASE_VERSION}"
curl --fail --location --proto '=https' --tlsv1.2 "$RELEASE_BASE/dentora-release-manifest.json" -o "$OUT/.release-manifest.json"
curl --fail --location --proto '=https' --tlsv1.2 "$RELEASE_BASE/dentora-release-manifest.json.sha256" -o "$OUT/.release-manifest.json.sha256"
( cd "$OUT" && sha256sum -c .release-manifest.json.sha256 )
python - "$OUT/.release-manifest.json" "$OUT/.env.client.example" "$RELEASE_VERSION" "$RELEASE_REPOSITORY" <<'PY'
import json
from pathlib import Path
import re
import sys
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version, repository = sys.argv[3:]
if manifest.get("schema") != 1 or manifest.get("version") != version:
    raise SystemExit("release manifest version/schema mismatch")
images = manifest.get("images", {})
for name in ("backend", "frontend"):
    if not re.fullmatch(r"ghcr\.io/.+@sha256:[0-9a-f]{64}", str(images.get(name, ""))):
        raise SystemExit(f"invalid immutable {name} image in release manifest")
p = Path(sys.argv[2])
text = p.read_text(encoding="utf-8")
values = {
    "DENTORA_VERSION": version,
    "DENTORA_BACKEND_IMAGE": images["backend"],
    "DENTORA_FRONTEND_IMAGE": images["frontend"],
    "DENTORA_RELEASE_REPOSITORY": repository,
}
for key, value in values.items():
    text = re.sub(rf"(?m)^{re.escape(key)}=.*$", f"{key}={value}", text)
p.write_text(text, encoding="utf-8")
PY
rm -f "$OUT/.release-manifest.json" "$OUT/.release-manifest.json.sha256"

grep -q '^LICENSE_SERVER_URL=..' "$OUT/.env.client.example"
grep -q '^LICENSE_PUBLIC_KEY_B64=..' "$OUT/.env.client.example"
grep -q '^DENTORA_BACKEND_IMAGE=ghcr.io/.\+@sha256:' "$OUT/.env.client.example"
grep -q '^DENTORA_FRONTEND_IMAGE=ghcr.io/.\+@sha256:' "$OUT/.env.client.example"

printf '%s\n' \
  "Dentora Licensed Generic Client local production package" \
  "Branch: $BRANCH" \
  "Created: $(date -Iseconds)" \
  "Reusable package: yes" \
  "Per-install secrets: generated on first start" \
  "Commercial license enforcement: enabled" \
  "License server: $LICENSE_SERVER_URL" \
  "Trial: disabled" \
  "Demo seed: disabled" \
  > "$OUT/BUILD_INFO.txt"

echo "[4/5] Creating ZIP..."
rm -f "$ZIP"
if command -v powershell.exe >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1; then
  WIN_OUT="$(cygpath -w "$OUT")"
  WIN_ZIP="$(cygpath -w "$ZIP")"
  powershell.exe -NoProfile -Command "Compress-Archive -Path '$WIN_OUT\\*' -DestinationPath '$WIN_ZIP' -Force" >/dev/null
elif command -v zip >/dev/null 2>&1; then
  (cd "$OUT" && zip -qr "$ZIP" .)
else
  echo "Could not create ZIP automatically. Package folder is ready at: $OUT"
  exit 0
fi

echo "[5/5] Verifying licensed generic package..."
test -f "$OUT/docker-compose.client.yml"
test -f "$OUT/.env.client.example"
test ! -e "$OUT/.env.client"
test -f "$OUT/START_DENTORA.bat"
test -f "$OUT/UPDATE_DENTORA.bat"
test -f "$OUT/scripts/client-update.ps1"
test -f "$OUT/CLIENT_INSTALL_AR.md"
test ! -e "$OUT/SET_CLIENT_PROFILE.bat"
test ! -e "$OUT/license-server"
test ! -e "$OUT/license-worker"
test ! -e "$OUT/.license-dev"
test -s "$ZIP"

echo
echo "READY"
echo "Folder: $OUT"
echo "ZIP:    $ZIP"
echo "This reusable ZIP requires a valid Dentora license key on every new installation."
