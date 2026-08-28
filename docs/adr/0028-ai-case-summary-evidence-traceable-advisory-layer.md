# ADR 0028 — AI Case Summary as an evidence-traceable advisory layer

**Status:** Accepted
**Date:** 2026-08-25

## Context

Case Intelligence provides the server-built, versioned Unified Clinical Case as a `CaseSnapshot`. An AI summary must not become a parallel source of clinical truth, leak free-text clinical notes to a cloud provider, or hide unavailable/stale source state.

## Decision

`ai_case_summary` consumes `CaseSnapshot` only. Before any cloud LLM invocation it creates a deterministic allowlisted projection that removes direct identifiers, source-record UUIDs and clinical free-text fields; the existing `app.core.agents.redaction.Redactor` is applied as a second privacy boundary. The module calls only the vendor-neutral `app.core.llm.base.Provider` abstraction.

Provider output is strict JSON. Each claim carries one or more evidence aliases that are validated against the snapshot projection. Every unavailable/stale section must be reproduced as an explicit data gap; generation is rejected if a gap is omitted or invented. The result is advisory, contains no risk score/threshold/clinical verdict contract, and is linked to the exact CaseSnapshot version/source digest plus provider/model/prompt/input/output provenance.

Generated results are `pending_review`. Only the clinic role `dentist` can accept or reject them. `clinical_output` becomes true only after dentist acceptance. AI Case Summary writes only its own summary/review records and events; canonical patient, anatomy, Dental3D, implant-planning and treatment data remain read-only sources.

No model weights or new AI package are added. The stage reuses the existing OpenAI-compatible provider path and therefore introduces no additional external model/license artifact.
