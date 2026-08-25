# ADR 0027 — Case Intelligence deterministic evidence layer

**Status:** Accepted  
**Date:** 2026-08-25

## Context

Later intelligence features require one reproducible representation of the current patient case. Dentora already owns canonical data across patients, patients_clinical, odontogram, periodontogram, patient_timeline, media and dental_3d. Copying conclusions or allowing clients to submit a canonical case would create unsafe drift.

## Decision

Introduce the `case_intelligence` module as an application/evidence layer.

1. A SQLAlchemy source adapter reads authoritative records only.
2. `CaseAggregator` normalizes ordered sections and computes a stable SHA-256 digest over the contract version, identity, availability, evidence and source state.
3. Missing sources are `not_available`. Existing but unaccepted/stale validated sources are `invalid_or_stale`. Neither status implies a clinical value.
4. Native validated CBCT/DICOM and IOS sources are independently available when present. Accepted alignment is the only source of unified patient-space reference-frame metadata; absence of alignment never fabricates a transform.
5. Materialized snapshots are append-only. If the latest digest matches, it is reused; if authoritative state changes, a new monotonically increasing snapshot version is inserted.
6. The HTTP API is GET-only and accepts no snapshot body. RBAC uses `case_intelligence.read`.
7. Snapshot creation publishes `case_intelligence.snapshot.created` after persistence with identifiers/version/digest only.
8. This module contains no diagnosis, risk score, clinical threshold, risk map, LLM/model call, AI narrative or treatment recommendation.

## Consequences

- Identical source state produces identical deterministic content and repeated reads return the same persisted snapshot/version.
- Source changes are auditable as new immutable versions.
- Evidence remains traceable to source module/entity/record/version/digest.
- Canonical clinical modules remain independently owned and unmodified.
- Later intelligence stages may depend on this contract, but none are implemented by this ADR.
