# AI Treatment Planning

AI Treatment Planning is an advisory decision-support capability layered on the existing
`ai_case_summary` module. It produces append-only treatment-planning **draft options** and
does not create, edit, confirm, or execute canonical `treatment_plan` records.

## Safety and clinical governance

Generation is fail-closed. A draft can be generated only when the current patient
`CaseSnapshot` has both a dentist-accepted AI Case Summary and a dentist-accepted Risk
Engine result derived from the same `case_source_digest`. If either upstream review is
missing or stale, generation is rejected.

Only the existing deterministic redacted `CaseSnapshot` projection is sent through the
vendor-neutral `core.llm.Provider` abstraction. Clinical free-text and direct identifiers
remain outside the cloud LLM input boundary. Accepted summary claims and Risk Engine
factors are supplied as structured context; neither is treated as a diagnosis or clinical
authority.

Every generated step must cite known CaseSnapshot evidence aliases. Unknown evidence,
invented or omitted data gaps, duplicate option/step identifiers, and malformed structured
output fail validation. The prompt explicitly forbids invented diagnoses, anatomy,
measurements, medications, dosages, device sizes, surgical coordinates, thresholds, and
claims that an option is required, safe, optimal, completed, or approved.

## Review semantics

Every generated record starts as `pending_review`. Only a user with the dentist role and
`ai_case_summary.review` permission can accept or reject it. Acceptance records the
reviewer and timestamp but still does not mutate canonical treatment plans. The API
contract permanently exposes `applied_to_treatment_plan=false`; there is intentionally no
"apply", "simulate", or autonomous treatment-plan mutation endpoint in this stage.

## Isolation and auditability

Persistence is scoped by `clinic_id` and `patient_id`. Reads, generation, history, and
review all use the authenticated clinic context. Each append-only version records:

- CaseSnapshot version, contract version, and source digest.
- Accepted AI Case Summary id/version/output digest.
- Accepted Risk Engine id/version/result digest.
- Provider, model, provider contract, and prompt versions.
- Deterministic input and output digests.
- Generator/reviewer ids and timestamps.

## API

The routes are mounted with the existing `ai_case_summary` module router:

- `POST /patients/{patient_id}/treatment-planning`
- `GET /patients/{patient_id}/treatment-planning/latest`
- `GET /patients/{patient_id}/treatment-planning/history`
- `POST /treatment-planning/{plan_id}/review`

The module's existing `read`, `generate`, and `review` RBAC permissions apply.

## Scope boundary

Treatment Simulation is explicitly outside this stage. No simulation engine, outcome
prediction, automatic procedure execution, or canonical treatment-plan write path is
introduced here.
