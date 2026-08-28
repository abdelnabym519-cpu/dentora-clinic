# Orthodontic Simulator

Dentora's Orthodontic Simulator is an independently removable, local-only deterministic
movement sandbox. It is not a biological outcome predictor, diagnosis, treatment approval,
or aligner-manufacturing system.

## Scope

- Canonical FDI tooth identity.
- Explicit millimetre coordinate frames.
- Dentist-reviewed per-tooth geometry gate.
- Deterministic cap-sized stage sequencing.
- Translation and cumulative transform contracts.
- Tip/torque/rotation rendering only when a trusted tooth-local frame exists.
- Scale/frame fail-closed checks.
- Deterministic movement warnings, reproducibility digests and optional static AABB proximity warnings.

## Dental3D boundary

Dental3D is read-only. The simulator reads its scene and latest accepted alignment but never
writes a scene, changes a mesh, starts segmentation, runs CBCT/nerve/implant processing or
creates a second storage abstraction. The current Dental3D contract exposes real intraoral
scans at whole-arch level but does not expose reviewed real per-tooth mesh mappings. Therefore
patient-specific movement currently reports `translation_eligible=false`; this is intentional
and must not be bypassed by accepting client-supplied mesh mappings.

## Safety invariants

- Source meshes are immutable references.
- Whole-arch geometry without reviewed per-tooth mapping cannot move.
- Translation requires reviewed per-tooth geometry plus an accepted trusted mm frame.
- Tip, torque and rotation require a trusted tooth-local frame; the current Dental3D contract
  does not provide one, so these remain non-renderable.
- Geometry/frame/provenance are server-owned and cannot be supplied by the client.
- Results are transient deterministic visualization data only; they never mutate the canonical treatment plan.

## Runtime

The core requires only the dependencies already present in Dentora. It makes no OpenAI,
ONNX, CUDA, model-download, cloud or external-service calls.

See `NOTICE` for the Apache-2.0 OpenSource Ortho attribution and the pinned compatibility-gate revision.
