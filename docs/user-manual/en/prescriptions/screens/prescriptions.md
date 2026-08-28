---
module: prescriptions
screen: prescriptions
route: /prescriptions
related_endpoints:
  - POST /api/v1/prescriptions
  - GET /api/v1/prescriptions
  - GET /api/v1/prescriptions/{prescription_id}
  - PATCH /api/v1/prescriptions/{prescription_id}
  - POST /api/v1/prescriptions/{prescription_id}/issue
  - POST /api/v1/prescriptions/{prescription_id}/cancel
  - POST /api/v1/prescriptions/{prescription_id}/void
  - GET /api/v1/prescriptions/{prescription_id}/audit
related_permissions:
  - prescriptions.read
  - prescriptions.write
  - prescriptions.issue
  - prescriptions.cancel
  - prescriptions.void
  - prescriptions.audit
related_paths:
  - backend/app/modules/prescriptions/frontend/pages/prescriptions/index.vue
  - backend/app/modules/prescriptions/router.py
last_verified_commit: e01a74e
---

# Electronic Prescriptions

The **Electronic Prescriptions** screen lets authorized clinical users create, issue, review, cancel, and void prescriptions inside the currently selected clinic. Prescription records are tenant- and clinic-isolated; lifecycle rules are enforced by the backend even if a control is unavailable or manipulated in the browser.

## Create a draft

> Requires `prescriptions.write`.

1. Open **Prescriptions** from the main navigation.
2. Search for a patient and select the correct clinic-scoped result.
3. Enter at least one medication with its medication name, dose, frequency, duration, route, and quantity. Strength, quantity unit, and instructions are optional where clinically appropriate.
4. Use **Add medication** when the prescription needs additional items.
5. Select **Create draft**.

A draft remains editable by its prescribing dentist until it is issued or cancelled.

## Issue a prescription

> Requires `prescriptions.issue` and the prescribing dentist.

Select **Issue** on a valid draft. Issuing moves the prescription to `issued`; its patient and medication content become immutable. The screen keeps the issued prescription visible as a clinical record and removes draft-only controls.

## Cancel or void

- **Cancel** applies to a draft and requires `prescriptions.cancel` plus a reason.
- **Void** applies to an issued prescription and requires `prescriptions.void` plus a reason.

Both states are terminal and retained for auditability. The module does not provide a delete action.

## Permissions

| Action | Permission |
|--------|------------|
| View prescription list/details | `prescriptions.read` |
| Create/edit drafts | `prescriptions.write` |
| Issue a draft | `prescriptions.issue` |
| Cancel a draft | `prescriptions.cancel` |
| Void an issued prescription | `prescriptions.void` |
| Read lifecycle audit events | `prescriptions.audit` |

Dentists receive the full clinical lifecycle by default; hygienists and assistants are read-only, and receptionists do not receive prescription access by default.

## Troubleshooting

- **A patient does not appear in search:** confirm that the patient belongs to the currently selected clinic and that you have access to that clinic.
- **Create draft is disabled:** select a patient first and provide valid medication data.
- **Issue/Cancel/Void is unavailable:** the action may not be valid for the current lifecycle state, you may lack its permission, or you may not be the prescribing doctor.
- **A terminal prescription cannot be edited:** this is intentional. Issued, cancelled, and voided prescriptions are immutable.
