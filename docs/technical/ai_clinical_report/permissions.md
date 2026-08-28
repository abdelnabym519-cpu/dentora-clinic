# AI Clinical Report permissions

The module declares two permissions:

| Permission | Purpose | Default roles |
| --- | --- | --- |
| `ai_clinical_report.read` | Read report readiness/status for a patient. | admin, dentist, hygienist |
| `ai_clinical_report.generate` | Generate a non-canonical draft report. | dentist |

`generate` also performs an explicit runtime dentist-role check. This intentionally prevents a broader RBAC wildcard from bypassing clinical control.

Both endpoints require the existing `ai` license feature. Clinic context is mandatory, and every upstream read is scoped to the authenticated clinic and requested patient.
