# AI Second Review — Permissions

AI Second Review is clinic-scoped and uses the standard Dentora module permission system.

| Permission | Purpose | Default roles |
|---|---|---|
| `ai_second_review.read` | Read generated reviews/history | admin, dentist, hygienist, assistant |
| `ai_second_review.generate` | Generate a new advisory review from an accepted planning/simulation chain | dentist |
| `ai_second_review.review` | Mark the advisory review as dentist-reviewed | dentist |

The service re-checks the dentist role for review acknowledgement even after router RBAC. Cross-clinic artifact lookups are filtered by `clinic_id` and `patient_id`.

`ai_second_review.review` does **not** approve a treatment plan. It only records that a dentist reviewed the AI Second Review artifact; canonical treatment records remain unchanged.
