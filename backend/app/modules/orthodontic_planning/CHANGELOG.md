# Changelog

## [0.1.0] - 2026-09-02

### Added

- Orthodontic planning module (backend): models (`ortho_assessments`,
  `ortho_plan_proposals`), schemas, service, router, isolated Alembic
  branch `ortho_0001`.
- Deterministic decision-support planner `heuristic_v1`: staged tooth
  movements (rotation/uprighting/proclination/distalization/
  retroclination) sliced at conservative per-stage caps.
- Deterministic constraint/safety layer: per-stage and per-tooth
  bounds, missing/deciduous-tooth refusal, one-movement-per-tooth,
  overjet and non-extraction space envelopes; hard violations refuse
  and audit the plan (never persisted).
- Planning provider abstraction (`PlanningProvider` protocol + named
  registry + fail-closed resolution via `ORTHO_PLANNING_PROVIDER`);
  extension point for future offline-trained ML/RL policies. No
  weights or training shipped.
- Data sufficiency gate: planning refuses (HTTP 422) listing missing
  measurements / under-charted odontogram.
- Clinician review lifecycle `draft → approved/rejected` with auditor
  events (`proposal_created`, `proposal_reviewed`, `plan_refused`).
- Capabilities endpoint exposing provider, constraint version, limits
  and envelopes.
- Frontend layer: patient summary card with sufficiency status,
  proposal list, deterministic score/confidence/uncertainty and review
  actions; i18n (en/es/fr/pt).
- Unit tests (domain/constraints/planner/registry) + API tests
  (RBAC, failure paths, refusal, events) with deterministic fixtures.
