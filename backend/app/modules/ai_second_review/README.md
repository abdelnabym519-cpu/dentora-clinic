# AI Second Review

AI Second Review is Dentora's evidence-traceable advisory consistency review over one dentist-accepted AI Treatment Planning option and its deterministic Treatment Simulation.

It does not diagnose, choose treatment, approve/reject a plan, predict biological outcomes, or mutate canonical clinical records. Generation fails closed unless the current Case Intelligence snapshot, deterministic Risk Engine result, accepted planning provenance, and Treatment Simulation all remain coherent and current.

## Safety invariants

- AI Treatment Planning must already be dentist-accepted with complete review provenance.
- Treatment Simulation must point to that exact accepted planning artifact/version/output digest and selected option.
- Current CaseSnapshot/Risk digests must match both planning and simulation provenance.
- The simulation input digest and scene are deterministically recomputed before review; any input/scene/output digest mismatch is rejected.
- Cloud LLM input is structured/redacted and excludes raw patient identifiers, raw clinical notes, and patient-space UIDs.
- Findings may reference only supplied evidence, risk factors, planning items, or simulation checkpoints.
- Missing/stale source sections remain explicit data gaps.
- Empty findings never imply safety, correctness, optimality, or approval.
- A dentist must review the generated artifact before `clinical_output=true`.
- Dentist review acknowledges this advisory artifact only; it does not approve treatment.

## API

- `POST /patients/{patient_id}` — generate a review for an explicit `simulation_id`.
- `GET /patients/{patient_id}/latest` — latest clinic-scoped review.
- `GET /patients/{patient_id}/history` — append-only history.
- `POST /results/{review_id}/review` — dentist-only acknowledgement of the advisory artifact.

The plugin framework namespaces these routes under `ai_second_review` and applies module permissions.
