#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-deploy/client-local}"
ROOT="$(git rev-parse --show-toplevel)"
DIST="$ROOT/dist"
OUT="$DIST/DentalPin_Client"
ZIP="$DIST/DentalPin_Client.zip"

echo "=== DentalPin Client Package ==="
echo "Source branch: $BRANCH"

command -v git >/dev/null || { echo "git is required"; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required (Git Bash includes it on most installs)"; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"

echo "[1/4] Exporting tracked client branch..."
git archive --format=tar "$BRANCH" | tar -x -C "$OUT"

# Remove deployment/development files that are not needed on the clinic PC.
rm -rf "$OUT/.github"
rm -f \
  "$OUT/docker-compose.yml" \
  "$OUT/docker-compose.prod.yml" \
  "$OUT/.env.prod.example" \
  "$OUT/railway.frontend.toml" \
  "$OUT/backend/railway.toml"

# Keep only the client launcher as the obvious compose entry point.

echo "[2/4] Generating per-install secrets..."
cp "$OUT/.env.client.example" "$OUT/.env.client"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"
SECRET_KEY="$(openssl rand -hex 32)"
BUDGET_PUBLIC_SECRET_KEY="$(openssl rand -hex 32)"

sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$POSTGRES_PASSWORD/" "$OUT/.env.client"
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" "$OUT/.env.client"
sed -i "s/^BUDGET_PUBLIC_SECRET_KEY=.*/BUDGET_PUBLIC_SECRET_KEY=$BUDGET_PUBLIC_SECRET_KEY/" "$OUT/.env.client"

# The generated env contains installation secrets; do not copy it back into git.
chmod 600 "$OUT/.env.client" 2>/dev/null || true

printf '%s\n' \
  "DentalPin Client local production package" \
  "Branch: $BRANCH" \
  "Created: $(date -Iseconds)" \
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

echo "[4/4] Verifying package..."
test -f "$OUT/docker-compose.client.yml"
test -f "$OUT/.env.client"
test -f "$OUT/START_DENTALPIN.bat"
test -f "$OUT/CLIENT_INSTALL_AR.md"
test -s "$ZIP"

echo
echo "READY"
echo "Folder: $OUT"
echo "ZIP:    $ZIP"
echo "Copy the ZIP to the client PC, extract it to C:\\DentalPin, then follow CLIENT_INSTALL_AR.md."
