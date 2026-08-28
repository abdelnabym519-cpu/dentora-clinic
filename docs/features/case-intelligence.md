# Case Intelligence

Case Intelligence provides a deterministic, server-built Unified Clinical Case snapshot for downstream evidence-based features.

## API

`GET /api/v1/case_intelligence/patients/{patient_id}` returns the current materialized snapshot. If authoritative inputs are unchanged, the existing latest version is reused. If they changed, the server appends a new version.

`GET /api/v1/case_intelligence/patients/{patient_id}?version=N` reads an existing immutable version and never rebuilds it.

The API accepts no client-supplied CaseSnapshot.

## Availability

Each section is one of:

- `available`: authoritative data meeting that source's validation contract is present.
- `not_available`: no authoritative source is present.
- `invalid_or_stale`: source records exist but do not meet the current accepted/closed validation state.

Missing data is never mapped to `0`, `normal`, `safe`, `negative`, or an inferred clinical meaning.

## Determinism and provenance

The aggregator orders sections and evidence, serializes source values canonically and computes a SHA-256 source digest. Important sections include source module, entity, record identifier, source version/digest and validation state where available.

Validated IOS meshes and CBCT/DICOM series remain available in their native source spaces even before registration. Accepted patient-specific IOS→CBCT alignment alone supplies the unified patient-space reference frame. Anatomy, nerve, prosthetic and alignment records remain owned by `dental_3d`; odontogram, periodontogram, clinical history, timeline and media remain owned by their source modules.

## Safety boundary

This stage is informational infrastructure. It contains no diagnosis, risk scoring, thresholds, verdicts, AI-generated narrative, LLM/model calls, autonomous treatment recommendation, automatic clinical approval or 3D risk rendering.
