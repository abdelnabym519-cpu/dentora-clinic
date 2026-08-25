# AI Case Summary invariants

- Input is a `CaseSnapshot` from `case_intelligence`; never rebuild clinical truth here.
- Cloud LLM input is the allowlisted projection from `privacy.py`. Raw UUID identifiers and clinical free-text are excluded before provider invocation.
- The module uses `app.core.llm.base.Provider` and `app.core.llm.factory.get_provider`; no vendor SDK is imported here.
- Output is advisory only. No diagnosis, clinical verdict, treatment recommendation, threshold, risk score, risk band or risk map belongs in this module.
- Every generated claim must reference evidence aliases that exist in the source snapshot. Missing/stale data is explicit and complete.
- A generated summary starts as `pending_review`; only a user whose clinic role is exactly `dentist` can accept/reject it. `clinical_output` is true only after acceptance.
- The module may persist its own summaries/review metadata. It must never write patient, anatomy, Dental3D, implant-planning, treatment, or other canonical source records.
- Domain/application/persistence contracts stay renderer-neutral; no Three/Tres/Three.js types.
- Provider responses are schema-validated and fail closed when claims reference unknown evidence or data gaps do not match the snapshot.
- Provider/model, prompt contract, input digest and output digest are persisted for reproducible provenance.
- Generated/review audit events must contain identifiers and digests only; summary clinical text must never be placed on the event bus.
- No new model weights or AI runtime dependencies may be introduced without explicit license and commercial-use review.
