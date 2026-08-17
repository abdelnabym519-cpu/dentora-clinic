#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-deploy/client-local}"
ROOT="$(git rev-parse --show-toplevel)"
DIST="$ROOT/dist"
OUT="$DIST/DentalPin_Generic_Client"
ZIP="$DIST/DentalPin_Generic_Client.zip"

echo "=== DentalPin Generic Client Package ==="
echo "Source branch: $BRANCH"

command -v git >/dev/null || { echo "git is required"; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"

echo "[1/4] Exporting tracked generic client branch..."
git archive --format=tar "$BRANCH" | tar -x -C "$OUT"

# Remove deployment/development files that are not needed on the clinic PC.
rm -rf "$OUT/.github"
rm -f \
  "$OUT/docker-compose.yml" \
  "$OUT/docker-compose.prod.yml" \
  "$OUT/.env.prod.example" \
  "$OUT/railway.frontend.toml" \
  "$OUT/backend/railway.toml" \
  "$OUT/.env.client"

# The generic ZIP deliberately contains no installation secrets.
# START_DENTALPIN.bat generates unique secrets on each clinic PC the first time it runs.
echo "[2/4] Preparing reusable first-run configuration..."
test -f "$OUT/.env.client.example"

printf '%s\n' \
  "DentalPin Generic Client local production package" \
  "Branch: $BRANCH" \
  "Created: $(date -Iseconds)" \
  "Reusable package: yes" \
  "Per-install secrets: generated on first start" \
  "Trial: disabled" \
  "Demo seed: disabled" \
  > "$OUT/BUILD_INFO.txt"

echo "[3/4] Creating ZIP..."
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

echo "[4/4] Verifying generic package..."
test -f "$OUT/docker-compose.client.yml"
test -f "$OUT/.env.client.example"
test ! -e "$OUT/.env.client"
test -f "$OUT/START_DENTALPIN.bat"
test -f "$OUT/CLIENT_INSTALL_AR.md"
test ! -e "$OUT/SET_CLIENT_PROFILE.bat"
test -s "$ZIP"

echo
echo "READY"
echo "Folder: $OUT"
echo "ZIP:    $ZIP"
echo "This ZIP can be reused for multiple clinics. Each extracted installation creates its own secrets on first start."
