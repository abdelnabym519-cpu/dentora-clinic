# Clinical Copilot

Clinical Copilot is a read-only clinical decision-support surface. It consumes existing append-only evidence artifacts instead of generating or mutating canonical patient data.

## Evidence chain

The service reads the latest clinic-scoped artifacts for Case Intelligence, Risk Engine, AI Treatment Planning and Treatment Simulation. Each downstream artifact is checked against the upstream contract version, artifact version, review provenance and digests it claims to consume. Treatment Planning must be dentist-accepted with reviewer/timestamp provenance. AI Second Review is consumed through a dedicated read-only port and must likewise carry accepted-review provenance; if that upstream contract is unavailable, the stage is reported as unavailable and advice fails closed.

## Advisory boundary

Clinical Copilot does not diagnose, prescribe, approve treatment, choose between options, or write to canonical clinical records. Advisory generation is dentist-only at both the HTTP surface and service boundary. The LLM receives no tools and any attempted tool call is rejected.

## Privacy

Only structured evidence is sent to the provider. The advice request accepts a finite `focus` enum rather than unrestricted clinical free text. Upstream payloads pass through the existing Dentora `Redactor` after a stricter clinical projection removes direct identifiers, source-record identifiers and unrestricted narrative/note fields. Missing, unavailable and stale inputs remain explicit and block advice rather than being inferred.

## Provenance

Every response contains provider/model identity, input and output digests, generator identity and the exact upstream stage/provenance statuses used for generation. Every claim must cite an evidence identifier that existed in the supplied evidence chain; unsupported evidence references fail closed.

## API

- `GET /api/v1/clinical-copilot/patients/{patient_id}/context`
- `POST /api/v1/clinical-copilot/advise`

Both endpoints are clinic-scoped and protected by RBAC plus the AI license feature gate. Only the dentist role may generate clinical advice; configured clinical roles may inspect read-only readiness/provenance.
