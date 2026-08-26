---
module: prescriptions
last_verified_commit: e01a74e
---

# Electronic Prescription — technical overview

The `prescriptions` module implements Dentora's clinic-selected, tenant-isolated electronic prescription lifecycle. It follows the module architecture used by the rest of Dentora: pure lifecycle rules in `domain.py`, application orchestration in `use_cases.py` against protocols from `ports.py`, SQLAlchemy adapters in `repository.py`, and FastAPI transport in `router.py`.

## Lifecycle and invariants

A prescription starts as `draft` and can transition to `issued` or `cancelled`; an issued prescription can transition to `voided`. Issued, cancelled, and voided prescriptions are immutable. Issuing requires at least one validated medication item, while cancellation and voiding require a reason. Only the prescribing doctor can mutate or transition the prescription.

There is intentionally no DELETE endpoint. Terminal clinical records are retained and lifecycle transitions are captured as append-only audit events.

## Tenant and clinic isolation

Every use case receives the authenticated `ClinicContext`. Client payloads cannot choose the tenant, clinic, prescribing doctor, identifier, status, audit actor, or lifecycle timestamps. Repository reads and writes are scoped by both `tenant_id` and `clinic_id`, and patient association is accepted only when the patient belongs to the selected clinic.

## Data model and migrations

The module owns three tables on the `prescriptions` Alembic branch (`rx_0001`):

- `prescriptions` — prescription identity, patient/doctor ownership, clinic/tenant scope, lifecycle status and transition timestamps/reasons.
- `prescription_items` — ordered medication instructions attached to one prescription.
- `prescription_audit_events` — append-only lifecycle audit records without duplicated medication/PHI payloads.

The branch depends on core revision `0007` and patients revision `pat_0003`. It must also be listed in `backend/alembic.ini` `version_locations`, because Alembic constructs its CLI revision graph before `env.py` can add dynamically discovered paths.

## API surface

Mounted at `/api/v1/prescriptions`:

- `POST /api/v1/prescriptions` — create a draft.
- `GET /api/v1/prescriptions` — list prescriptions in the selected tenant/clinic; optional patient and status filters.
- `GET /api/v1/prescriptions/{prescription_id}` — read one prescription in scope.
- `PATCH /api/v1/prescriptions/{prescription_id}` — edit draft content only.
- `POST /api/v1/prescriptions/{prescription_id}/issue` — issue a draft.
- `POST /api/v1/prescriptions/{prescription_id}/cancel` — cancel a draft with a reason.
- `POST /api/v1/prescriptions/{prescription_id}/void` — void an issued prescription with a reason.
- `GET /api/v1/prescriptions/{prescription_id}/audit` — read lifecycle audit events.

## Frontend

`backend/app/modules/prescriptions/frontend/pages/prescriptions/index.vue` exposes `/prescriptions`. It uses the existing clinic-scoped Patients API to select a patient, creates medication items using the backend contract, and renders lifecycle controls only when the current status permits them. Issued and terminal prescriptions are presented as immutable.

## Permissions

The module declares `read`, `write`, `issue`, `cancel`, `void`, and `audit`. See [`permissions.md`](./permissions.md) for endpoint and role mapping.

## See also

- `backend/app/modules/prescriptions/README.md`
- `backend/app/modules/prescriptions/CLAUDE.md`
- `backend/app/modules/prescriptions/migrations/versions/rx_0001_initial.py`
