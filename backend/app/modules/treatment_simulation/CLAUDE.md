# Treatment Simulation

## Purpose

`treatment_simulation` renders a deterministic, non-predictive timeline for one explicitly selected option from a dentist-accepted AI Treatment Planning artifact. It reuses the current Case Intelligence snapshot, accepted patient-space coordinates, Risk Engine/Risk Map, and the existing Dental Digital Twin renderer contract.

## Safety boundary

- A simulation can be generated only from an AI Treatment Planning artifact with `review_status=accepted`, `clinical_output=true`, and complete dentist review provenance.
- The current CaseSnapshot source/version/contract and Risk Engine version/policy/input/result digests must exactly match the evidence reviewed with the accepted plan; stale plans fail closed.
- The current CaseSnapshot must expose an accepted DICOM patient-space reference frame.
- The caller must choose `planning_id` and `option_id`; this module never ranks or selects treatment options.
- Checkpoints copy reviewed planning steps only. They have `geometry_operation=none` and `predicted_outcome=false`.
- The Dental Digital Twin scene has `synthetic_geometry=false` and `mutates_source_geometry=false`.
- The module does not predict biological response, create synthetic anatomy, or create/update/execute a canonical treatment plan.
- AI Second Review is outside this module and must not be added here.

## Public API

- `POST /api/v1/treatment_simulation/patients/{patient_id}` — create/reuse a simulation for an explicit accepted planning option.
- `GET /api/v1/treatment_simulation/patients/{patient_id}/latest` — latest clinic-scoped simulation.
- `GET /api/v1/treatment_simulation/patients/{patient_id}/history` — append-only history.

## Permissions

- `read`
- `generate` — dentist only in the role manifest; the service additionally enforces the accepted-plan safety gate.

## Architecture

`simulator.py` is a pure deterministic domain builder. `service.py` orchestrates Case Intelligence, Risk Engine evaluation, accepted planning provenance, stale-input validation, deterministic hashing, and append-only persistence through ports in `ports.py`. `repository.py` supplies clinic-scoped SQLAlchemy adapters. `contracts.py` carries the versioned Dental Digital Twin scene and provenance contract.

## Persistence and provenance

Artifacts are append-only per patient and include clinic/patient identity, simulation version, accepted planning artifact/version/output digest/reviewer/timestamp, CaseSnapshot version/contract/source digest, Risk Engine and policy versions plus input/result digests, deterministic simulation input/output digests, generator identity, and the exact scene payload.

## Gotchas

Do not turn a planning checkpoint into predicted geometry. Do not relax stale-evidence comparisons to make an old accepted plan simulatable. Do not add writes into `treatment_plan`, `odontogram`, implant planning, budget, scheduling, prescriptions, or Dental3D source geometry.
