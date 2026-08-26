# Treatment Progress Intelligence

## Purpose

Treatment Progress Intelligence is a read-only operational view of an existing treatment plan. It turns the authoritative treatment-plan item and session states into a compact progress snapshot without changing clinical data or the plan state machine.

It is deliberately deterministic. It does not diagnose patients, predict clinical outcomes, or recommend a treatment.

## API

`GET /api/v1/treatment-plans/{plan_id}/progress-intelligence`

Permission: `treatment_plan.plans.read`.

The response reports:

- item counts for `completed`, `pending`, and `cancelled`;
- session counts for the same states;
- completion percentages excluding cancelled rows from the actionable denominator;
- the first pending item according to the existing `sequence_order`;
- the most recent item/session completion time and days since that completion;
- the next non-cancelled/non-no-show appointment linked to a plan item;
- a deterministic operational state: `not_started`, `in_progress`, `needs_scheduling`, `completed`, or `closed`.

## Tenant and ownership boundary

The plan is loaded through `TreatmentPlanService.get(db, clinic_id, plan_id)`, which scopes the read by both plan id and clinic id. The appointment lookup begins from clinic-scoped planned-treatment items and uses the same relationship path as the existing treatment-plan pipeline query. A plan from another clinic therefore resolves as not found.

## Data and architecture impact

- No migration.
- No new database table or stored derived score.
- No event emission.
- No state mutation.
- No new cross-module dependency; `agenda` is already in `treatment_plan.manifest.depends`.
- Existing treatment and session states remain the single source of truth.
