---
module: orthodontic_simulator
last_verified_commit: 96f180e8a1aaf118c23183eff504ca5f4a3e8a34
---

# Orthodontic Simulator — permissions

`OrthodonticSimulatorModule.get_permissions()` returns the relative names `read` and `write`; the Dentora registry namespaces them as `orthodontic_simulator.read` and `orthodontic_simulator.write`.

| Permission | Allows | Required by |
|---|---|---|
| `orthodontic_simulator.read` | Read the patient-specific capability result and fail-closed eligibility reasons. | `GET /api/v1/orthodontic_simulator/patients/{patient_id}/capability` |
| `orthodontic_simulator.write` | Request a transient deterministic staged movement simulation after all server-side geometry/frame safety gates pass. | `POST /api/v1/orthodontic_simulator/patients/{patient_id}/simulate` |

## Role assignment

Declared by the module manifest in `backend/app/modules/orthodontic_simulator/__init__.py`:

| Role | Permissions |
|---|---|
| admin | `*` |
| dentist | `*` |
| hygienist | `read` |
| assistant | `read` |
| receptionist | none |

The write permission does not authorize mutation of Dental3D source geometry or canonical treatment plans. The simulator service remains fail-closed when reviewed per-tooth geometry, trusted millimetre coordinates, or required tooth-local frames are unavailable.

When permissions change, update the manifest role mapping and endpoint gates together, update this file, and regenerate the module catalogs with `python backend/scripts/generate_catalogs.py`.
