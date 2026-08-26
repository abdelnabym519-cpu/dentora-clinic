# AI Treatment Planning — permissions

- `ai_treatment_planning.read`: read generated planning artifacts and history.
- `ai_treatment_planning.generate`: request advisory planning options from the current CaseSnapshot and deterministic risk context.
- `ai_treatment_planning.review`: enter the review endpoint. The application additionally requires `ClinicContext.role == "dentist"`; wildcard/admin permission alone cannot accept AI planning output as clinical.

Role defaults: dentist = read/generate/review; admin = read/generate; hygienist/assistant = read; receptionist = none.
