# Prescriptions module

Electronic Prescription owns the clinic-scoped prescription lifecycle for Dentora.
It is clinical data and must remain tenant-isolated, clinic-isolated, auditable, and RBAC-protected.

## Public API

Routes are mounted at `/api/v1/prescriptions`.
Draft creation and editing require `prescriptions.write`.
Issuing requires `prescriptions.issue`.
Cancellation requires `prescriptions.cancel`.
Voiding requires `prescriptions.void`.
Audit history requires `prescriptions.audit`.
Reading and listing require `prescriptions.read`.

## Dependencies

`manifest.depends = ["patients"]`.
Patient association must be validated through the Patients boundary for the selected clinic.
Do not add direct cross-module business-logic imports when a port or core contract is available.

## Lifecycle

The supported transitions are `draft → issued → voided` and `draft → cancelled`.
Issued, cancelled, and voided prescription content is immutable.
Issuing requires at least one valid medication item.
Cancellation and voiding require a non-empty reason.
Only the prescribing doctor may mutate or transition the prescription.

## Isolation and security

Every persistence read and write must filter both `tenant_id` and `clinic_id`.
Tenant, clinic, doctor, identifier, status, audit actor, and lifecycle timestamps are server-controlled.
There is intentionally no DELETE API for prescriptions or audit history.
Audit records are append-only through the application boundary.
Do not copy medication or patient PHI into audit metadata unnecessarily.

## Architecture

Pure lifecycle rules belong in `domain.py`.
Use cases in `use_cases.py` depend on protocols from `ports.py`.
SQLAlchemy and patient-access adapters belong in `repository.py`.
FastAPI dependency wiring and HTTP translation belong in `router.py`.
Infrastructure concerns must not leak into the domain aggregate.

## Frontend

The Nuxt layer exposes `/prescriptions`.
Patient search uses the existing clinic-scoped Patients API.
Lifecycle controls must only expose transitions valid for the current status.
Terminal prescription content is rendered read-only.

## Migrations

Module migrations live under `migrations/versions` and use the `prescriptions` branch label.
Migration changes must remain reversible and pass the repository Alembic round-trip gate.

## CHANGELOG

See `./CHANGELOG.md`.
