# Treatment Simulation

Treatment Simulation is Dentora's deterministic visualization layer for an already dentist-accepted AI Treatment Planning option.

It reuses the current Case Intelligence snapshot as the source of truth, the accepted patient-space reference frame from Dental 3D alignment, the deterministic Risk Engine/Risk Map, and the existing `dental_3d.digital_twin` renderer contract. The simulation does **not** generate synthetic anatomy, move teeth or implants, predict biological response, or create/update the canonical treatment plan.

## Safety invariants

- A planning artifact must have `review_status=accepted` and complete reviewer provenance.
- The current CaseSnapshot and Risk Engine digests must exactly match the evidence that was reviewed with the planning artifact. Stale plans are rejected.
- A valid accepted DICOM patient-space reference frame is required.
- Every timeline checkpoint is copied from the explicitly selected planning option and keeps its evidence/risk-factor references.
- Viewer output contains `synthetic_geometry=false`, `mutates_source_geometry=false`, and each checkpoint has `geometry_operation=none`.
- Clinic scoping is enforced on every planning and simulation repository lookup.
- Simulation artifacts are append-only and content-addressed by deterministic input/output digests.

## API

- `POST /patients/{patient_id}` — create/reuse a simulation for an explicit `{planning_id, option_id}`.
- `GET /patients/{patient_id}/latest` — latest simulation for the current clinic/patient.
- `GET /patients/{patient_id}/history` — append-only simulation history.

The plugin framework namespaces these routes under the `treatment_simulation` module and applies module permissions.
