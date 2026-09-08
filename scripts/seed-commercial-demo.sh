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
# Runs entirely inside the Linux backend container, so it is portable across
# Windows (Git Bash / WSL) and Linux/macOS without any host-Python or
# host-path dependency.
#
# Usage:
#   ./scripts/seed-commercial-demo.sh
#
set -euo pipefail

echo "============================================================"
echo "Dentora Commercial Sales Demo Seeder"
echo "============================================================"

echo "[1/2] Base demo cascade (skips silently if already present)..."
docker compose exec -T backend bash -c \
  "PYTHONPATH=/app python /app/scripts/seed_demo.py --lang en"

echo ""
echo "[2/2] Golden Demo Patient (AI-input clinical source state)..."
docker compose exec -T backend bash -c \
  "PYTHONPATH=/app python -m app.seeds.commercial_golden"

echo ""
echo "Done. Open the app and look up patient 'Golden Demo Patient'."
echo "============================================================"
