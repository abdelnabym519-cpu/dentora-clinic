---
module: dental_3d
last_verified_commit: 66f01c8
---

# dental_3d — permissions

Returned by `Dental3DModule.get_permissions()` (relative names — the
registry namespaces them as `dental_3d.<name>`).

| Permission | Allows | Required by |
|------------|--------|-------------|
| `dental_3d.read` | Fetching a patient's dental 3D scene (geometry sources, normalized CBCT series availability + persisted view state). | `GET /patients/{id}/scene`, agent tool `get_patient_scene`, the `patient.summary.cards` slot entry. |
| `dental_3d.write` | Persisting per-tooth 3D view state and ingesting real scan meshes or validated CT DICOM instances. | `PUT /patients/{id}/scene`, `POST /patients/{id}/meshes`, `POST /patients/{id}/cbct/dicom-instances`, the card's mesh-upload control. |

Mesh and DICOM **content** downloads ride the media module's own route
(`/api/v1/media/documents/{id}/download`, `media.documents.read`) —
scene mesh `url`s are issued server-side, and every role holding
`dental_3d.read` today also holds `media.documents.read` (media
manifest: admin/dentist/assistant/receptionist `*`, hygienist
`documents.read`). Patient/clinic ownership is always resolved
server-side from the authenticated context; uploads for unknown or
cross-clinic patients return 404, and `PUT` payloads carrying
tooth-level mesh descriptors are rejected with 422 (meshes are
server-derived).

## Role assignment

Declared in the module manifest
([`backend/app/modules/dental_3d/__init__.py`](../../../backend/app/modules/dental_3d/__init__.py)):

| Role          | Permissions    | Notes |
|---------------|----------------|-------|
| admin         | `*`            | Full control. |
| dentist       | `*`            | Views and adjusts the 3D preview. |
| hygienist     | `read`, `write`| Chairside use. |
| assistant     | `read`         | View-only. |
| receptionist  | _none_         | No clinical access — the summary card stays hidden. |

See `backend/app/core/auth/permissions.py` for the canonical role
table. Frontend mirror: `frontend/app/config/permissions.ts`
(`PERMISSIONS.dental3d.*`).

## Adding a new permission

1. Add the relative name to `get_permissions()` in
   `backend/app/modules/dental_3d/__init__.py`.
2. Add it to the role mapping in `manifest.role_permissions` (same
   file).
3. Wire the gate on the endpoint via
   `Depends(require_permission("dental_3d.<name>"))`.
4. Mirror in `frontend/app/config/permissions.ts`.
5. Add a row to the table above.
