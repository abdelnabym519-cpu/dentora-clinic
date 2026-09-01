# AI Second Review

## Purpose

`ai_second_review` audits the traceability and internal consistency of the existing Case Intelligence → Risk Engine → dentist-accepted AI Treatment Planning → deterministic Treatment Simulation chain. It is advisory decision support only.

## Safety boundary

- Never diagnose, choose/recommend treatment, or emit a treatment approval/rejection.
- Never create/update/execute `treatment_plan`, odontogram, implant-planning, prescription, scheduling, billing, media, or Dental3D source records.
- Require accepted AI Treatment Planning plus complete dentist-review provenance.
- Fail closed if current CaseSnapshot/Risk provenance differs from either the planning or simulation artifact.
- Recompute the deterministic simulation input digest and scene, requiring exact input/scene/output-digest agreement before any LLM call.
- Preserve patient-space safety locally while excluding patient-space UIDs from cloud LLM input.
- Send structured/redacted data only; raw clinical notes/free text are not part of the cloud path.
- Every generated finding must reference known evidence, risk factors, planning items, or simulation checkpoints.
- Preserve all `not_available` and `invalid_or_stale` sections as explicit data gaps.
- `clinical_output` stays false until a dentist reviews the generated review artifact.
- Dentist review is acknowledgement of the advisory review only; it is not treatment approval.

## Public API

- `POST /api/v1/ai_second_review/patients/{patient_id}`
- `GET /api/v1/ai_second_review/patients/{patient_id}/latest`
- `GET /api/v1/ai_second_review/patients/{patient_id}/history`
- `POST /api/v1/ai_second_review/results/{review_id}/review`

## Permissions

- `read`
- `generate` — dentist only in the role manifest.
- `review` — dentist only in the role manifest and re-checked in the service.

## Architecture

`privacy.py` builds the redacted structured LLM projection. `generator.py` owns strict JSON/provider validation and reference allowlists. `service.py` validates the artifact chain, rebuilds Treatment Simulation deterministically, invokes the existing LLM provider abstraction, and persists append-only results through ports in `ports.py`. `repository.py` supplies clinic-scoped SQLAlchemy adapters.

## Persistence and provenance

Each artifact records CaseSnapshot/Risk versions and digests, accepted planning identity/version/output/reviewer provenance, simulation identity/version/engine/input/output digests, provider/model/prompt/input contract provenance, and deterministic input/output digests for the review itself.

## Gotchas

Do not turn findings into treatment recommendations or a pass/fail verdict. Do not relax stale-chain checks to review old artifacts. Do not send reference-frame UIDs or raw clinical notes to the cloud provider. Do not infer that no findings means clinically safe.
