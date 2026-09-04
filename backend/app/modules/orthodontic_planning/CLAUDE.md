# Orthodontic planning module

ML/RL **decision support** for orthodontics: deterministic staged
tooth-movement proposals, gated by a hard safety layer and mandatory
clinician review. It never prescribes autonomously, never writes to
other modules, and ships no trained model.

## Public API

- Routes mounted at `/api/v1/orthodontic_planning/`.
- Key endpoints:
  - `GET    /capabilities`                       — provider + envelope info; permission `orthodontic_planning.read`
  - `POST   /patients/{pid}/assessments`         — record measurements; permission `orthodontic_planning.write`
  - `GET    /patients/{pid}/assessments`         — history; permission `orthodontic_planning.read`
  - `GET    /assessments/{aid}`                  — detail (snapshot + sufficiency); permission `orthodontic_planning.read`
  - `POST   /assessments/{aid}/plan`             — run planner → draft proposal; permission `orthodontic_planning.write`
  - `GET    /patients/{pid}/proposals`           — history; permission `orthodontic_planning.read`
  - `GET    /proposals/{id}`                     — detail incl. constraint report; permission `orthodontic_planning.read`
  - `POST   /proposals/{id}/review`              — approve/reject (draft only); permission `orthodontic_planning.write`
  - `DELETE /proposals/{id}`                     — remove; permission `orthodontic_planning.write`

## Dependencies

`manifest.depends = ["patients", "odontogram"]`. Both are read-only
queries; the dentition snapshot is copied JSONB (no cross-module FK).

## Permissions

`orthodontic_planning.read`, `orthodontic_planning.write`. Roles →
permissions live in the manifest (admin `*`, dentist read+write,
hygienist/assistant read, receptionist none).

## Tools exposed

None by design — planning is clinician-facing, not an agent surface
(`get_tools()` returns `[]` so the copilot registry stays clean).

## Events emitted

| Event | When | Payload keys |
|---|---|---|
| `orthodontic_planning.proposal_created` | valid plan persisted as draft | `proposal_id`, `assessment_id`, `patient_id`, `clinic_id`, `provider`, `status`, `stage_count` |
| `orthodontic_planning.proposal_reviewed` | clinician approves/rejects | `proposal_id`, `patient_id`, `clinic_id`, `decision`, `reviewed_by`, `reviewed_at` |
| `orthodontic_planning.plan_refused` | provider output fails the safety gate (not persisted) | `clinic_id`, `patient_id`, `assessment_id`, `provider`, `provider_version`, `hard_violations` |

## Events consumed

None.

## Safety architecture (read before touching)

1. `domain.py` — pure data structures + FDI helpers + sufficiency.
2. `constraints.py` — the single deterministic gate; **hard violation ⇒
   refusal, never persistence**. Sits *outside* the provider.
3. `planner/base.py` — provider Protocol + registry; unknown provider
   ⇒ `ProviderUnavailableError` → HTTP 503 (fail closed).
4. `planner/heuristic.py` — shipped deterministic reference policy
   (no ML weights anywhere in the repo).
5. Review lifecycle: `draft → approved/rejected` only; no code path
   executes a proposal.

## Gotchas

- Changing any bound in `constants.py` requires bumping
  `CONSTRAINTS_VERSION` (it is stamped on every proposal for audit).
- `generate_proposal()` re-validates provider output; do not persist
  from the provider layer.
- Assessment rows are immutable snapshots; corrections = new row.
