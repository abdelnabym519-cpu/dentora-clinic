# Clinical Copilot

Clinical Copilot is a read-only clinical decision-support surface. It consumes existing append-only evidence artifacts instead of generating or mutating canonical patient data.

## Evidence chain

The service reads the latest clinic-scoped artifacts for Case Intelligence, Risk Engine, AI Treatment Planning and Treatment Simulation. Each downstream artifact is checked against the upstream version and digest it claims to consume. AI Second Review is consumed through a dedicated read-only port; if that upstream contract is unavailable, the stage is reported as unavailable and advice fails closed.

## Advisory boundary

Clinical Copilot does not diagnose, prescribe, approve treatment, choose between options, or write to canonical clinical records. The dentist remains the decision maker. The LLM receives no tools and any attempted tool call is rejected.

## Privacy

Only structured evidence is sent to the provider. The advice request accepts a finite `focus` enum rather than unrestricted clinical free text. Direct-identifier keys and unrestricted free-text note fields in upstream structured artifacts are removed before transmission. Missing and stale inputs are preserved as explicit states rather than inferred.

## Provenance

Every response contains provider/model provenance and an input digest. Every claim must cite an evidence identifier that existed in the supplied evidence chain; unsupported evidence references fail closed.

## API

- `GET /api/v1/clinical-copilot/patients/{patient_id}/context`
- `POST /api/v1/clinical-copilot/advise`

Both endpoints are clinic-scoped and protected by RBAC plus the AI license feature gate. Only the dentist role receives `clinical_copilot.use`; read-only readiness/provenance may be exposed to configured clinical roles.
