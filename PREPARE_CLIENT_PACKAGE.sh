#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-feature/license-activation}"
ROOT="$(git rev-parse --show-toplevel)"
DIST="$ROOT/dist"
OUT="$DIST/Dentora_Client"
ZIP="$DIST/Dentora_Client.zip"
LICENSE_SERVER_URL="${DENTORA_LICENSE_SERVER_URL:-}"
LICENSE_PUBLIC_KEY_B64="${DENTORA_LICENSE_PUBLIC_KEY_B64:-}"

echo "=== Dentora Licensed Generic Client Package ==="
echo "Source branch: $BRANCH"

command -v git >/dev/null || { echo "git is required"; exit 1; }

if [[ -z "$LICENSE_SERVER_URL" || -z "$LICENSE_PUBLIC_KEY_B64" ]]; then
  echo "ERROR: Commercial package build requires the pinned license service configuration."
  echo "Set DENTORA_LICENSE_SERVER_URL and DENTORA_LICENSE_PUBLIC_KEY_B64 first."
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

echo "[3/5] Preparing reusable first-run configuration..."
test -f "$OUT/.env.client.example"

grep -q '^LICENSE_SERVER_URL=..' "$OUT/.env.client.example"
grep -q '^LICENSE_PUBLIC_KEY_B64=..' "$OUT/.env.client.example"

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
