# AI Clinical Report

## Purpose

`ai_clinical_report` creates an advisory draft report from the already-reviewed clinical evidence chain.
It never diagnoses, approves treatment, prescribes, or writes a canonical patient/treatment record.

## Public API

- `GET /api/v1/ai_clinical_report/patients/{patient_id}/readiness`
- `POST /api/v1/ai_clinical_report/generate`

## Safety contract

Generation fails closed unless Case Intelligence, Risk Engine, AI Treatment Planning, Treatment Simulation, and AI Second Review are all current and review-complete.
Only a dentist may generate a report even if a broader RBAC wildcard would otherwise match.
The output status is always `draft` and `dentist_review_required=true`.
No endpoint mutates canonical clinical records.

## AI and privacy

The module reuses the existing Clinical Copilot guarded service and vendor-neutral LLM provider.
The provider receives only the existing structured/redacted/opaque-ID projection.
Clinical free text and direct identifiers are not introduced by this module.
Claims are accepted only when the upstream Copilot validates their evidence IDs.
Report assembly is deterministic and rejects any claim that cannot be mapped back to upstream evidence.

## Provenance

The report carries provider/model metadata, source advisory input/output digests, its own output digest, the complete upstream stage status chain, generation time, and generating dentist.
The AI Second Review adapter is read-only and scoped by clinic and patient.

## Permissions

- `ai_clinical_report.read` — readiness only.
- `ai_clinical_report.generate` — dentist-controlled draft generation.

## Events and persistence

The module emits and consumes no events.
It owns no database model or migration in v1 because reports are non-canonical drafts returned to the requesting dentist.
