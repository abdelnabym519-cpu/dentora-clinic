# Orthodontic Planning — Overview

**Module:** `orthodontic_planning` v0.1.0 · **Type:** ML/RL clinical decision support
**Status:** shipped as API-first decision support with a minimal patient-summary card

## Purpose

Generates orthodontic **plan proposals** (staged tooth movements) for a
patient case, as *decision support only*. The system never prescribes
autonomously: every proposal is a draft document that a clinician must
explicitly approve or reject, and approval triggers no clinical action
by itself.

## Architecture (Clean Architecture, inside the module boundary)

```
router.py        HTTP + RBAC + error mapping only
service.py       orchestration: case building → provider → safety gate → persistence + audit
domain.py        pure structures: FDI helpers, Movement/Stage, PlannerCase, sufficiency
constraints.py   deterministic safety gate (the single validator for ALL plans)
planner/base.py  PlanningProvider protocol + named registry (fail-closed)
planner/heuristic.py  shipped deterministic reference policy (heuristic_v1)
models.py        ortho_assessments / ortho_plan_proposals (isolated Alembic branch)
```

Key property: **the model never talks to the database**. Providers
receive a frozen `PlannerCase` and return a frozen `PlanSuggestion`;
the service re-validates that suggestion through `constraints.
evaluate_stages` regardless of which provider produced it. Hard
violations ⇒ refusal + `plan_refused` audit event + nothing persisted.

## Data flow

1. Clinician records an **assessment** (measurements + objectives).
   The module snapshots the patient's odontogram (read-only query) and
   computes a deterministic **data-sufficiency** report.
2. `POST /assessments/{id}/plan` resolves the configured provider
   (`ORTHO_PLANNING_PROVIDER`, default `heuristic_v1`). Insufficient
   data ⇒ HTTP 422 listing exactly what to chart (fail closed).
3. The suggestion is re-validated; a valid plan persists as a **draft
   proposal** with score, confidence, uncertainty notes and the full
   constraint report, and emits `proposal_created`.
4. A user with `orthodontic_planning.write` **reviews** it
   (`draft → approved|rejected`, one transition, audited).

## ML/RL posture (honesty statement)

No trained model, no weights, no training data exist in this
repository. The shipped planner is a transparent deterministic
reference policy. The `PlanningProvider` protocol + registry + the
deterministic reward (`score_proposal`) + the movement-bound semantics
are the extension point where an **offline-trained ML/RL policy** can
be integrated once curated longitudinal outcome data exists. Any such
policy remains subject to the same constraint gate and review
lifecycle. See `safety.md`.

## Not in scope (v1)

- Extractive/surgical planning, transverse (RME) mechanics, IPR
  staging, biomechanical simulation, growth modification.
- Consuming approved proposals into treatment plans (manual clinical
  act, separate module flow).
