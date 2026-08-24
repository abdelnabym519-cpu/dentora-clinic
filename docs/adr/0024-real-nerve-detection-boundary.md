# ADR 0024 — Real nerve detection boundary

- Status: Accepted
- Date: 2026-08-24
- Supersedes: ADR 0022 production-provider decision (historical contracts and
  persisted rows remain compatible)

## Context

Phase 4 proved the review and visualization workflow with canonical demo
anatomy. Phase 5.2 must accept real CBCT input without claiming a trained model
that the repository does not contain, and without beginning patient-specific
registration or implant/surgical planning.

## Decision

Retain `NerveDetectionProvider` as the application-facing port and make a new
infrastructure adapter the sole production composition-root choice. The
adapter acquires patient-owned media, creates a bounded de-identified and
deterministic DICOM archive, invokes an operator-controlled HTTP inference
service, strictly validates its output, and returns native DICOM-patient
geometry plus confidence, uncertainty and provenance.

An absent or invalid service is a structured `missing_model` or
`model_initialization_failed` outcome. Production must never fall back to
canonical coordinates. Non-failed inference requires review; failures contain
no anatomical finding. Native findings cannot be drawn in another modality's
frame until a separately authorized alignment phase exists.

## Consequences

- Model/runtime choice stays replaceable and outside domain/application code.
- DICOM pixel data can cross only the explicit operator-configured inference
  trust boundary after allowlist sanitization; identifiers and free text do not.
- No large ML dependency or untrusted weight deserialization is introduced.
- The repository can validate acquisition → inference boundary → normalization
  without pretending its controlled service response is trained-model proof.
- Actual model execution remains unverified until approved weights/runtime,
  deployment resource limits and clinical validation evidence are supplied.

## Explicit non-decisions

No CBCT↔IOS/face registration, multimodal fusion, tooth/nerve distance,
implant planning, surgical guide/trajectory, pathology detection, autonomous
recommendation or clinical-accuracy claim is included.
