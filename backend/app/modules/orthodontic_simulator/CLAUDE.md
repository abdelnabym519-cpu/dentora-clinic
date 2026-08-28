# orthodontic_simulator module

Orthodontic Simulator is Dentora's independently removable, local-only deterministic orthodontic movement sandbox. It is a visualization/planning draft tool only: it does not predict biology, diagnose, approve treatment, generate aligners, or mutate the canonical treatment plan.

## Public API

Routes are mounted under `/api/v1/orthodontic_simulator/`:

- `GET /patients/{patient_id}/capability` — read-only eligibility and fail-closed reasons; permission `orthodontic_simulator.read`.
- `POST /patients/{patient_id}/simulate` — transient deterministic staging over server-owned reviewed geometry; permission `orthodontic_simulator.write`.

## Dependencies and boundaries

`manifest.depends = ["patients", "dental_3d"]`.

Dental3D is strictly read-only. The module reads the assembled scene and latest alignment but never writes a scene, uploads a mesh, starts segmentation, changes CBCT/nerve/implant state, or creates another storage abstraction. Source geometry remains owned by Dental3D/media.

The current Dental3D contract exposes real intraoral meshes at whole-arch level but does not expose a reviewed real per-tooth mesh mapping or a trusted per-tooth local frame. Therefore current patient-specific movement fails closed: translation is disabled without reviewed per-tooth geometry plus an accepted trusted millimetre frame, and tip/torque/rotation remain disabled until a trusted tooth-local frame exists.

## Domain

`domain.py` is framework-free Pydantic/deterministic code:

- canonical FDI identity;
- explicit millimetre coordinate frames;
- immutable patient-derived geometry references with SHA-256 provenance;
- `ToothDelta`, contiguous `Stage`, configurable movement heuristics and cumulative poses;
- scale/frame/rotation safety findings;
- deterministic cap-sized staging;
- canonical reproducibility digest;
- optional static AABB proximity warnings only.

No database, HTTP client, cloud, OpenAI, ONNX, CUDA, model runtime or model-download code exists in the domain.

## Frontend

The removable Nuxt layer uses only Dentora's existing Vue/Nuxt, TresJS and Three.js stack. It registers one permission-gated `patient.summary.cards` slot. The displayed arch is an explicitly non-patient schematic FDI selector; it never receives patient transforms. Numeric movement, stage playback and before/after/overlay controls remain locked whenever the server capability gate is false.

## Safety invariants

- Patient source meshes are immutable references.
- Whole-arch geometry without reviewed per-tooth mapping cannot move.
- Geometry IDs, coordinate frames and provenance are server-owned; clients cannot supply them to bypass the gate.
- Translation requires reviewed per-tooth geometry and accepted trusted mm coordinates.
- Tip, torque and long-axis rotation require a trusted tooth-local frame.
- Simulation results always declare `clinical_prediction=false`, `treatment_approval=false`, `synthetic_geometry=false`, and `mutates_source_geometry=false`.
- No write path touches `treatment_simulation` or Dental3D internals.

## Lifecycle

- `installable=True` / `auto_install=False` / `removable=True`.
- The module stores no database state and returns no SQLAlchemy models.
- `ortho_sim_0001` is an intentionally no-op isolated Alembic branch marker so removal is graph-isolated without inventing persistence.

## Licensing

Deterministic orthodontic planning concepts are selectively adapted from OpenSource Ortho under Apache-2.0 at pinned audit revision `f5f93fc56fd406614abca5e608d28c991d2f7f12`; see `NOTICE`. No OpenSource Ortho cloud/model extras are included. No OrthoViz source code is copied because that repository did not provide a software license during audit.
