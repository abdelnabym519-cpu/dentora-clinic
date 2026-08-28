# Treatment Simulation — Technical Overview

## Purpose

`treatment_simulation` provides deterministic decision-support visualization for a dentist-selected option from an **accepted** AI Treatment Planning artifact. It does not forecast treatment success, biological response, tooth movement, implant migration, or any other future anatomy.

## Architecture

The module follows the existing plugin/Clean Architecture pattern:

- `contracts.py` defines the versioned public result, provenance, timeline, and Dental Digital Twin scene contracts.
- `simulator.py` is a pure domain service that transforms reviewed planning steps into non-predictive checkpoints.
- `ports.py` defines persistence/read interfaces used by the application service.
- `repository.py` contains clinic-scoped SQLAlchemy adapters.
- `service.py` orchestrates Case Intelligence, Risk Engine/Risk Map, AI Treatment Planning review state, deterministic hashing, caching, and append-only persistence.
- `router.py` exposes permission-protected endpoints.

## Evidence and Digital Twin reuse

The current `CaseSnapshot` is always materialized through Case Intelligence. The simulation accepts only `reference_frame.status=available` and forwards the accepted patient-space metadata unchanged to the scene. Available Dental 3D source sections are referenced as baseline Digital Twin inputs rather than copied or mutated.

The Risk Engine is re-evaluated against that current snapshot. Its Risk Map is forwarded unchanged. The current snapshot version/digest and Risk Engine input/result digests must exactly match those recorded on the accepted AI Treatment Planning artifact. Any mismatch produces `accepted_treatment_planning_is_stale` and no simulation is created.

## Review and provenance

Only `review_status=accepted` AI Treatment Planning artifacts with `reviewed_at` and `reviewed_by` provenance can be simulated. The caller explicitly supplies both `planning_id` and `option_id`; the simulation engine does not rank or choose an option.

Every persisted simulation records:

- clinic/patient identity and append-only simulation version;
- accepted planning artifact/version/output digest/reviewer/timestamp;
- CaseSnapshot version/contract/source digest;
- Risk Engine and policy versions plus input/result digests;
- deterministic simulation input/output digests;
- exact scene payload and generator identity.

## Safety properties

Each checkpoint is a display stage only: `geometry_operation=none` and `predicted_outcome=false`. The scene contract fixes `synthetic_geometry=false` and `mutates_source_geometry=false`. This makes Treatment Simulation a reviewed-plan visualization layer rather than a predictive clinical engine.

The module deliberately does not implement a second AI review; that belongs to a later stage.
