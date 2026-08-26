---
module: copilot
last_verified_commit: 0000000
---

# Copilot — technical overview

The `copilot` module has two deliberately separate surfaces. The existing operational chat consumes registered tools under the caller's RBAC permissions. Clinical Copilot is an advisory-only clinical surface that reads the reviewed Case Intelligence → Risk Engine → AI Treatment Planning → Treatment Simulation workflow and exposes no tools.

## Clinical Copilot safety contract

Clinical Copilot is mounted at `POST /api/v1/copilot/clinical/patients/{patient_id}/advice`. The request accepts only a finite `focus` enum; arbitrary clinical free text is rejected before the provider boundary. The application service additionally requires the caller's clinic role to be `dentist` before any LLM call.

The provider receives a structured projection produced through the existing AI Treatment Planning privacy/redaction boundary. Patient identifiers and free-text clinical-note fields are excluded. The LLM is invoked with `tools=[]`, and its JSON output is rejected unless every claim traces to known evidence, risk factors, reviewed planning options, or simulation checkpoints.

The surface fails closed unless the latest planning artifact is dentist-accepted and the Treatment Simulation provenance still matches the current CaseSnapshot and deterministic Risk Engine digests. Any `invalid_or_stale` case section blocks generation. `not_available` data remains explicit and must be repeated by the provider as a limitation.

Clinical Copilot does not diagnose, approve treatment, select or execute a treatment plan, predict biological outcomes, or create/update canonical clinical records. It may materialize the existing append-only Case Intelligence snapshot through that module's normal service contract.

## Existing operational API surface

- `GET /api/v1/copilot/sessions`
- `GET /api/v1/copilot/sessions/{conversation_id}/messages`
- `GET /api/v1/copilot/settings`
- `PATCH /api/v1/copilot/settings`
- `POST /api/v1/copilot/sessions`
- `POST /api/v1/copilot/sessions/{conversation_id}/confirmations/{call_id}`
- `POST /api/v1/copilot/sessions/{conversation_id}/end`
- `POST /api/v1/copilot/sessions/{conversation_id}/messages`

## Permissions

The clinical endpoint reuses `copilot.chat` at the router boundary so the module manifest remains backwards compatible, then applies a stricter dentist-only application gate before any provider call. Existing permissions remain `chat`, `history.read`, `history.read_all`, `supervise`, and `configure`.

## See also

- Module notes: `backend/app/modules/copilot/CLAUDE.md`
- AI Treatment Planning privacy boundary: `backend/app/modules/ai_treatment_planning/privacy.py`
- Treatment Simulation contracts: `backend/app/modules/treatment_simulation/contracts.py`
- [Documentation portal contract](../../technical/documentation-portal.md)
