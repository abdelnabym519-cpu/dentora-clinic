---
module: orthodontic_simulator
last_verified_commit: 96f180e8a1aaf118c23183eff504ca5f4a3e8a34
---

# Orthodontic Simulator — technical overview

Orthodontic Simulator is an independently removable, local deterministic visualization sandbox. It stages tooth movement only when reviewed per-tooth Dental3D geometry and the required trusted coordinate-frame provenance are available. It is not a biological prediction, diagnosis, treatment approval, aligner generator, or canonical treatment-plan writer.

Module code lives at `backend/app/modules/orthodontic_simulator/` and is mounted under `/api/v1/orthodontic_simulator/`.

## API surface

| Verb | Path | Permission |
|---|---|---|
| GET | `/patients/{patient_id}/capability` | `orthodontic_simulator.read` |
| POST | `/patients/{patient_id}/simulate` | `orthodontic_simulator.write` |

Both routes are clinic-scoped through the standard Dentora clinic context. The capability endpoint is read-only. The simulation endpoint computes transient deterministic stages and does not persist or mutate Dental3D source geometry.

## Dependencies and boundaries

The manifest declares `depends = ["patients", "dental_3d"]`, `installable=True`, `auto_install=False`, and `removable=True`.

Dental3D is consumed read-only. The simulator does not change Dental3D internals, upload meshes, start segmentation, modify CBCT/nerve/implant state, or write into `treatment_simulation`. Patient source geometry remains owned by Dental3D/media.

## Safety model

- Whole-arch geometry alone is insufficient for tooth movement.
- Translation requires reviewed per-tooth geometry plus an accepted trusted millimetre frame.
- Tip, torque, and long-axis rotation require a trusted tooth-local frame.
- Geometry identifiers and provenance are server-owned so clients cannot bypass the capability gate.
- Missing or stale required provenance fails closed.
- Simulation output is deterministic and transient and never mutates source geometry.

## Migration and lifecycle

The module stores no database state and returns no SQLAlchemy models. Its isolated no-op Alembic branch marker, `ortho_sim_0001`, exists only to keep install/remove lifecycle graph isolation without inventing persistence.

## Frontend

The removable Nuxt layer uses the existing Vue/Nuxt, TresJS, and Three.js stack. The patient-summary card exposes schematic FDI tooth selection and movement controls, but patient-specific movement controls remain disabled whenever the backend capability gate is false.

For the complete module boundary and licensing notes, see [`backend/app/modules/orthodontic_simulator/CLAUDE.md`](../../../backend/app/modules/orthodontic_simulator/CLAUDE.md).
