# Treatment Simulation — Permissions

Treatment Simulation is clinic-scoped and uses the standard Dentora module permission system.

| Role | `treatment_simulation.read` | `treatment_simulation.generate` |
| --- | --- | --- |
| admin | Yes | No |
| dentist | Yes | Yes |
| hygienist | Yes | No |
| assistant | Yes | No |
| receptionist | No | No |

## Generate

`treatment_simulation.generate` permits creation/reuse of a deterministic simulation for an explicit `planning_id` and `option_id`. The application service still enforces the clinical gate independently of RBAC: the planning artifact must already be dentist-reviewed and `accepted`, its review provenance must be complete, and its Case Intelligence/Risk Engine evidence must still be current.

## Read

`treatment_simulation.read` permits retrieval of the latest result and append-only history for a patient within the authenticated clinic. Repository queries include both `clinic_id` and `patient_id`, preventing cross-clinic lookup by identifier.

## No review permission

This module intentionally has no review/approve permission. It consumes the existing AI Treatment Planning review state and does not implement AI Second Review or a new clinical approval stage.
