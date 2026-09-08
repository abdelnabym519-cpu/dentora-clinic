#!/usr/bin/env bash
#
# Dentora Commercial Sales Demo — single entry point.
#
# Produces the commercial demo dataset in ONE command:
#   1. Base demo cascade  (clinic, users, patients, catalog, odontogram,
#      treatment plans, budgets, invoices, agenda, notes, timeline, ...).
#      No-op when the demo clinic already exists (idempotent guard inside).
#   2. Golden Demo Patient (rich, AI-input-ready clinical source state:
#      patients_clinical, odontogram, periodontogram, patient_timeline).
#      Idempotent — re-runs upsert, never duplicate.
#
# Windows / Git Bash safety
# -------------------------
# Git Bash (MSYS2) rewrites POSIX-absolute arguments (anything starting with
# `/`) into Windows paths before they reach Docker — e.g. `/app` becomes
# `C:/Program Files/Git/app`, which breaks `bash -c "... /app ..."` with
# "Files/Git/app: No such file or directory".
#
# This wrapper therefore NEVER passes a `/...`-looking token to Docker and
# never uses `bash -c`:
#   * it runs every command through `docker compose exec` (no inner shell);
#   * it relies on the backend image's WORKDIR=/app (./backend is volume
#     mounted at /app), so it uses RELATIVE paths only;
#   * the base seed needs `/app` importable, so it sets PYTHONPATH=. via
#     docker compose exec -e (a value with no leading slash → untouched);
#   * the golden seed is invoked as a module (`python -m app.seeds.…`),
#     which needs no absolute path either.
#
# The Python seeds run inside the Linux backend container, so there is no
# host-Python or host-path dependency. No destructive reset is performed; both
# steps are idempotent.
#
# Usage:
#   ./scripts/seed-commercial-demo.sh
#
set -euo pipefail

SERVICE="backend"

# ---------------------------------------------------------------------------
# 1. Ensure the backend container is running before we try to exec into it.
# ---------------------------------------------------------------------------
if [ -z "$(docker compose ps --status running -q "$SERVICE" 2>/dev/null)" ]; then
    echo "ERROR: '$SERVICE' container is not running."
    echo "Start the stack first, e.g.:  docker compose up -d db $SERVICE"
    exit 1
fi

echo "============================================================"
echo "Dentora Commercial Sales Demo Seeder"
echo "============================================================"

echo "[1/2] Base demo cascade (skips silently if already present)..."
# Relative script path (WORKDIR=/app). PYTHONPATH=. adds /app (the container
# working directory) to sys.path so the script can `import app`. No `/app`
# token reaches the shell, so Git Bash cannot mangle it.
docker compose exec -T -e PYTHONPATH=. "$SERVICE" python scripts/seed_demo.py --lang en

echo ""
echo "[2/2] Golden Demo Patient (AI-input clinical source state)..."
# Module invocation from WORKDIR=/app → `app` is importable; no paths passed.
docker compose exec -T "$SERVICE" python -m app.seeds.commercial_golden

echo ""
echo "Done. Open the app and look up patient 'Golden Demo Patient'."
echo "============================================================"
