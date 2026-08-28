---
module: prescriptions
last_verified_commit: e01a74e
---

# Electronic Prescription — permissions

`ElectronicPrescriptionModule.get_permissions()` declares six relative permissions. The registry exposes them under the `prescriptions.*` namespace, and every API operation also resolves the authenticated tenant and selected clinic through `ClinicContext`.

| Permission | Allows | Protected endpoints |
|------------|--------|---------------------|
| `prescriptions.read` | Read prescriptions in the selected clinic. | `GET /api/v1/prescriptions`, `GET /api/v1/prescriptions/{prescription_id}` |
| `prescriptions.write` | Create a draft and edit draft content owned by the prescribing doctor. | `POST /api/v1/prescriptions`, `PATCH /api/v1/prescriptions/{prescription_id}` |
| `prescriptions.issue` | Issue a valid draft, making its clinical content immutable. | `POST /api/v1/prescriptions/{prescription_id}/issue` |
| `prescriptions.cancel` | Cancel a draft with a recorded reason. | `POST /api/v1/prescriptions/{prescription_id}/cancel` |
| `prescriptions.void` | Void an issued prescription with a recorded reason. | `POST /api/v1/prescriptions/{prescription_id}/void` |
| `prescriptions.audit` | Read append-only prescription lifecycle audit events. | `GET /api/v1/prescriptions/{prescription_id}/audit` |

## Default role assignment

| Role | Prescription permissions |
|------|--------------------------|
| `admin` | `*` (all module permissions) |
| `dentist` | `read`, `write`, `issue`, `cancel`, `void`, `audit` |
| `hygienist` | `read` |
| `assistant` | `read` |
| `receptionist` | none |

Permission checks do not replace ownership or isolation rules: mutation/transition use cases also require the prescribing doctor, and repository queries remain tenant- and clinic-scoped.

## Changing permissions

When adding a permission, keep the module manifest role mapping, `get_permissions()`, FastAPI `require_permission(...)` dependency, relevant frontend gate, tests, and this document in sync.
