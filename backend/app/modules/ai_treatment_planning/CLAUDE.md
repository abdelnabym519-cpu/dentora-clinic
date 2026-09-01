# AI Treatment Planning

## Purpose

`ai_treatment_planning` generates advisory, evidence-traceable treatment-planning options from the current Case Intelligence snapshot and the deterministic Risk Engine evaluation of that same snapshot.

## Safety boundary

- Input to the cloud LLM is structured and deterministically redacted.
- Patient/clinic identifiers and clinical free-text fields are removed before provider invocation.
- Provider-visible clinical facts exist only under record-local `case.evidence[E###].facts`; parallel section `data` is removed.
- The provider selects only allowlisted advisory strategy codes, evidence IDs, scalar fact paths, and known risk-factor IDs.
- Dentora validates every selected fact path and renders all public option/step prose deterministically.
- Missing and stale sources are derived deterministically from the CaseSnapshot as explicit data gaps and are never delegated to the model.
- Output is advisory only and cannot create, update, confirm, price, schedule, or execute a canonical `treatment_plan` record.
- Treatment Simulation is explicitly outside this module and is not implemented here.
- Only a dentist can accept or reject a generated artifact; acceptance changes review state only.

## Public API

- `POST /api/v1/ai_treatment_planning/patients/{patient_id}` — generate an append-only planning artifact.
- `GET /api/v1/ai_treatment_planning/patients/{patient_id}/latest` — latest artifact in the active clinic.
- `GET /api/v1/ai_treatment_planning/patients/{patient_id}/history` — append-only history.
- `POST /api/v1/ai_treatment_planning/results/{planning_id}/review` — dentist accept/reject.

## Permissions

- `read`
- `generate`
- `review` — dentist only in the role manifest and re-checked in the service.

## Architecture

The application service depends on repository and generation ports. `SqlAlchemyPlanningRepository` is the persistence adapter, and `generate_planning_options` is the LLM adapter over the existing `core.llm.Provider` abstraction. Risk evaluation is deterministic and is computed from the exact CaseSnapshot used for the LLM input.

## Persistence and provenance

Artifacts are append-only per patient with clinic-scoped queries, case snapshot version/source digest, Risk Engine version/policy/input/result digests, provider/model/prompt/input/output digests, generator/reviewer identities, and review timestamps.

## Gotchas

Do not add automatic writes into `treatment_plan`, `budget`, `odontogram`, scheduling, prescriptions, or Dental3D. Do not reintroduce provider-authored clinical prose, parallel provider-facing section data, provider-authored data gaps, or evidence validation that checks aliases without validating record-local fact paths.
