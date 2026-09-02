# Orthodontic Planning — Permissions & RBAC

Module-namespaced grants declared in `manifest.role_permissions`
(merged by `app.core.auth.permissions.get_role_permissions`):

| Role | Grants |
|---|---|
| admin | `*` (everything) |
| dentist | `orthodontic_planning.read`, `orthodontic_planning.write` |
| hygienist | `orthodontic_planning.read` |
| assistant | `orthodontic_planning.read` |
| receptionist | — |

`get_permissions()` returns `["read", "write"]`; every endpoint
enforces one of the two via `require_permission(...)`:

- **read** — capabilities, assessments, proposals
- **write** — create assessment, generate plan, review, delete

## Tenancy

Every query is scoped by `clinic_id` from `get_clinic_context`; a
patient (or assessment/proposal) from another clinic resolves to 404,
never to a data leak. Verified by `test_cross_clinic_isolation`.

## Approval semantics

- Only `write` holders can review; the reviewer identity + timestamp
  are stored on the proposal (`reviewed_by`, `reviewed_at`) and echoed
  in the `proposal_reviewed` audit event.
- Review is final in v1: an approved/rejected proposal cannot
  transition again (409). Corrections = generate a new proposal.
