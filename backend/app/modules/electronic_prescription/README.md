# Electronic Prescription

Production Electronic Prescription module for Dentora. The module is clinic-selected and tenant-scoped at every repository read/write, and never accepts tenant, clinic, doctor, identifier, status, audit actor or lifecycle timestamps from client input.

## Lifecycle

`draft → issued → voided` or `draft → cancelled`. Issued, cancelled and voided prescriptions are immutable. Issuing requires at least one validated medication item. Cancellation and voiding require a reason. Only the prescribing doctor can mutate or transition a prescription.

## Medication contract

Each medication captures medication name, optional strength, dose, frequency, duration, route, quantity, optional quantity unit, and optional instructions.

## Security and auditability

- Authentication and selected-clinic resolution use the core `ClinicContext`.
- RBAC permissions: `prescriptions.read`, `.write`, `.issue`, `.cancel`, `.void`, `.audit`.
- Dentists receive the clinical mutation grants; hygienists/assistants are read-only; receptionists have no prescription grant; admins retain platform policy wildcard.
- Patient association is accepted only when the patient belongs to the selected clinic.
- Every repository query filters both `tenant_id` and `clinic_id`.
- Lifecycle mutation uses row locking and creates append-only audit records.
- Audit details store action metadata rather than medication/PHI payload copies.
- There is intentionally no DELETE API.

## API

Mounted at `/api/v1/prescriptions`:

- `POST /` create draft
- `GET /` list selected-clinic prescriptions
- `GET /{id}` read one
- `PATCH /{id}` edit draft content only
- `POST /{id}/issue`
- `POST /{id}/cancel`
- `POST /{id}/void`
- `GET /{id}/audit`

## Frontend

The Nuxt layer exposes `/prescriptions`. Patient selection uses the existing clinic-scoped Patients search API, medication fields mirror the backend contract, and lifecycle controls are rendered only for transitions valid from the current status. Issued/terminal prescriptions are displayed read-only. The Playwright flow covers dentist login, patient association, draft creation and issue/immutability.

## Architecture

Pure lifecycle rules live in `domain.py`. `use_cases.py` depends only on protocols in `ports.py`. SQLAlchemy patient/persistence adapters live in `repository.py`, and FastAPI wiring lives in `router.py`.
