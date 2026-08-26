# Risk Engine

## Purpose

Deterministic, append-only observed-fact decision support over the current versioned `CaseSnapshot`, plus a fail-closed 3D Risk Map presentation contract for the existing Dental3D ThreeUI.

## Architecture boundary

- `engine.py` is pure deterministic policy/domain logic. It consumes only `CaseSnapshot` contracts and never queries infrastructure.
- `service.py` owns application orchestration, tenant-scoped persistence, append-only versioning and dentist review.
- `models.py` stores derived results only. This module never mutates patients, anatomy, odontogram, periodontal, implant-planning or treatment records.
- The Risk Map reuses the existing Dental3D patient-space/ThreeUI pipeline. No renderer-space coordinates are persisted by this module.

## Clinical safety

Risk results are advisory only: `is_clinical=false`, `requires_review=true`, no auto-approval. The policy has no diagnostic labels, aggregate score, low/medium/high clinical bands, HU assumptions, bone-quality assumptions or clinical thresholds. Factors are exact structured observations or explicit `not_available` / `invalid_or_stale` gaps. Free-text notes/comments/narratives are never interpreted by the engine.

Risk display bands (`evidence_present`, `evidence_absent`, `data_gap`, `invalid_source`) describe evidence state only; they are not diagnoses or validated risk categories.

## Determinism and provenance

The input digest is computed from the CaseSnapshot linkage, engine/policy versions, reference frame and relevant structured sections. The result digest excludes timestamps and review state. Therefore identical input + engine/policy versions produce the same result digest, while a relevant source/snapshot change changes provenance/digests.

Every factor contains evidence aliases resolving to persisted source references. Persistence records snapshot version/contract, source digest, input digest, result digest, engine version, policy version, generated timestamp and availability state.

## 3D Risk Map

The map is `UNAVAILABLE` unless an accepted DICOM-patient/mm frame, accepted alignment and validated anatomy are available. Regions are built only from accepted patient-space evidence already present in CaseSnapshot (accepted nerve pathways and accepted current implant-plan geometry). Frame mismatch, missing evidence or invalid/stale sources fail closed. Synthetic geometry is forbidden.

## Review and permissions

- `risk_engine.read`: read latest/history.
- `risk_engine.generate`: materialize a new append-only result.
- `risk_engine.review`: dentist-only accept/reject transition from `pending_review`.

Acceptance records review provenance but does not turn the unvalidated Risk Engine into a diagnosis and does not mutate canonical clinical data.

## Open source

No new dependency, model or model weights are introduced. The Risk Map reuses the repository's existing Three.js/TresJS/three-mesh-bvh presentation stack and existing patient-space contracts; deterministic backend evaluation uses the Python standard library and existing Pydantic/SQLAlchemy infrastructure.

## Limitations / validation

This stage is not clinically validated and must not be used as an autonomous treatment decision. No numeric observation is converted into a clinical threshold. Implant/nerve intersection means only the existing explicit finite-implant-solid to accepted nerve-centerline geometric intersection semantics; it is not canal-wall clearance.
