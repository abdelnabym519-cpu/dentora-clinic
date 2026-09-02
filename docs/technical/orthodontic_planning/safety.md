# Orthodontic Planning — Safety & Constraint Policy

`CONSTRAINTS_VERSION`: `ortho-constraints-2026.09` (stamped on every
persisted proposal; bump on any bound change so audits can always
reconstruct which envelope produced a plan).

## Invariants (all enforced in code, all deterministic)

1. **Decision support only.** The module writes only its own two
   tables. It never mutates odontogram, treatment plans, or anything
   clinical. An approved proposal is a document — consuming it is a
   separate human act.
2. **No autonomous execution.** There is no code path that acts on an
   approved proposal. The only state machine is
   `draft → approved|rejected`.
3. **The model never touches the DB.** Providers get a frozen
   `PlannerCase`, return a frozen `PlanSuggestion`.
4. **One gate for every plan.** `constraints.evaluate_stages`
   validates heuristic and (future) learned output identically,
   *outside* the provider, in the service layer.
5. **Fail closed.** Missing/under-charted data ⇒ 422 with the gap
   list; unknown provider ⇒ 503; provider crash ⇒ 503; unsafe
   provider output ⇒ 422 + `plan_refused` audit event + **nothing
   persisted**.
6. **Uncertainty is explicit.** Every proposal carries `confidence`
   (≤ 0.9 for the deterministic policy) and `uncertainty` notes (mixed
   dentition, adult skeletal discrepancy, transverse limits, and the
   standing "no biomechanical simulation" disclosure).

## Hard violations (refuse the plan)

| Code | Rule |
|---|---|
| `H_EMPTY_PLAN` / `H_TOO_MANY_STAGES` | 0 stages or > 30 stages |
| `H_UNKNOWN_TOOTH` | tooth absent from the dentition snapshot |
| `H_MISSING_TOOTH` | tooth charted missing/extracted |
| `H_DECIDUOUS_TOOTH` | deciduous tooth (v1 plans permanent dentition only) |
| `H_MOVEMENT_TYPE` | type outside `MOVEMENT_LIMITS` |
| `H_STAGE_BOUND` | per-stage cap exceeded (e.g. translation 0.5 mm, rotation 10°) |
| `H_TOTAL_BOUND` | per-tooth cumulative cap exceeded (e.g. proclination 6 mm) |
| `H_ONE_MOVEMENT_PER_TOOTH` | same tooth moved twice in one stage |
| `H_OVERJET_ENVELOPE` | planned upper retroclination exceeds the overjet-reduction envelope (target 3 mm, non-surgical cap 6 mm) |

## Soft findings (persisted, surfaced to the reviewer)

| Code | Rule |
|---|---|
| `S_SPACE_DEFICIT` | arch crowding demand exceeds planned non-extraction relief (proclination ≤ 2/3 mm lower/upper + first-molar distalization ≤ 1 mm/side) — flagged for specialist decision |

## ML/RL policy

This phase ships **no trained model**. There is no orthodontic
outcome dataset in the repository, so training anything would be
dishonest. Delivered instead:

- the **provider abstraction** (`PlanningProvider` protocol, named
  registry, `ORTHO_PLANNING_PROVIDER` setting, fail-closed resolution);
- the **environment semantics** a future policy is evaluated against:
  immutable movement application + fixed caps (`domain`, `constraints`);
- the **reward specification**: `score_proposal` = 0.6·alignment
  resolution + 0.25·envelope adherence + 0.15·stage efficiency;
- the **reference policy** `heuristic_v1` (deterministic, CI-tested,
  self-validated through the same gate).

A future ML/RL provider must (a) register under its own name, (b)
quantify uncertainty in `PlanSuggestion`, (c) pass the same gate, and
(d) never gain write access — all four hold by construction of this
architecture.
