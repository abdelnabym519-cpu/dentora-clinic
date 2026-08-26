# AI Case Summary — permissions

- `ai_case_summary.read`: read generated summaries.
- `ai_case_summary.generate`: request a summary from the current CaseSnapshot.
- `ai_case_summary.review`: enter the review endpoint. The application additionally requires `ClinicContext.role == "dentist"`; wildcard/admin permission alone cannot accept AI output as clinical.

Role defaults: dentist = read/generate/review; admin = read/generate; hygienist/assistant = read; receptionist = none.
