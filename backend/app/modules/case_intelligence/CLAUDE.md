# Case Intelligence

## Purpose

Case Intelligence is the deterministic, versioned evidence layer for a unified patient case. It aggregates authoritative Dentora modules without mutating them.

## Invariants

- Informational infrastructure only: no diagnosis, risk score/band/threshold, clinical verdict, AI narrative, recommendation, or automatic approval.
- The server constructs snapshots from authoritative source records. Never accept client-supplied snapshots as canonical.
- Missing data is explicit `not_available`; rejected/pending/stale validated sources are `invalid_or_stale`.
- Never convert missing data to zero, normal, safe, negative, or inferred values.
- Persistence is append-only. Repeated reads with unchanged source digest reuse the latest version; source changes create a new version.
- Preserve provenance/evidence and patient-space metadata from accepted alignment.
- No Three/Tres/Three.js rendering type may cross into this module.
- Public HTTP surface is read-only: current materialization or retrieval of an existing version only.
