# Patient Presentation Mode — Agent Notes

## Scope

This module exposes an ephemeral chairside presentation derived only from the latest accepted AI Case Summary and current authoritative Case Intelligence inputs.

## Invariants

1. Dentist-controlled access only.
2. Never mutate canonical clinical records or upstream AI artifacts.
3. Never use a pending/rejected summary as patient-facing material.
4. Preserve claim evidence aliases and data-gap semantics verbatim.
5. Recompute the authoritative source digest read-only and fail closed if it differs from the accepted summary.
6. Do not add LLM calls, diagnosis, treatment decisions, autonomous approval, or generated patient claims.
7. Keep clinic isolation through the existing ClinicContext and upstream clinic-scoped queries.
8. Do not depend on Treatment Simulation, Clinical Copilot, AI Second Review, or AI Clinical Report.

## Validation

Run focused Patient Presentation tests, Ruff, the full backend/frontend validation, documentation/catalog checks, Full CI, and the storage/integration gate for the final SHA.
