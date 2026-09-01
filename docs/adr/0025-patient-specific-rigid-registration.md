# 0025 — Patient-specific rigid registration behind Dentora ports

- **Status:** accepted
- **Date:** 2026-08-25
- **Deciders:** Dentora Core Team
- **Tags:** dental-3d, registration, dicom, geometry, clinical-safety, licensing

## Context

IOS meshes have no reliable unit or patient-coordinate metadata. CBCT geometry
uses DICOM patient coordinates and must retain Frame of Reference, spacing,
orientation and origin. Overlaying the two without a measured registration
would create a false clinical relationship. DentalSegmentator can supply
patient-specific CBCT dental anatomy, while Open3D and TEASER++ provide rigid
point-cloud registration capabilities.

## Decision

Dentora computes IOS→CBCT SE(3) transforms through inner-layer input, anatomy
and registration ports. Infrastructure resolves patient-owned media,
de-identifies DICOM, calls an operator-managed DentalSegmentator service, and
runs Open3D RANSAC plus optional TEASER++ initialization followed by measured
ICP refinement. The selected transform, frames, units, input digests, model
identity, correspondence/overlap/residual metrics, failure and review state are
persisted append-only.

IOS units are mandatory input. DICOM Frame of Reference and full geometric
metadata are mandatory. No clinical threshold is inferred: the contract fixes
`CLINICAL_THRESHOLD_NOT_VALIDATED`, and a result remains pending/uncertain until
dentist acceptance or rejection.

## Consequences

### Good

- The transform is patient-specific, reproducible and traceable to exact input
  bytes and coordinate frames.
- External libraries/models remain replaceable and out of the domain layer.
- Failed or ambiguous geometry cannot silently become an overlay.
- Technical metrics and dentist review survive reloads.

### Bad / accepted trade-offs

- A configured DentalSegmentator service is required for successful runs.
- Open3D adds a large runtime dependency.
- TEASER++ bindings require an operator/system build on platforms without a
  compatible package; Open3D RANSAC remains the measured global candidate.
- No clinical accuracy claim or automatic acceptance is possible.

## Alternatives considered

- **Canonical arches, landmarks or fixed offsets** — rejected because they are
  not patient registration.
- **Non-rigid deformation** — rejected because it can hide poor rigid alignment
  and does not produce the required SE(3) transform.
- **3D Slicer as runtime** — rejected; it remains reference/validation tooling.
- **PyTorch/nnU-Net inside Dentora** — rejected; model execution stays behind an
  operator-managed service boundary.

## How to verify the rule still holds

- `backend/tests/modules/dental_3d/test_registration_domain.py`
- `backend/tests/modules/dental_3d/test_registration_infrastructure.py`
- `backend/tests/modules/dental_3d/test_registration_service.py`
- `backend/tests/modules/dental_3d/test_registration_api.py`
- `rg "import (open3d|teaserpp_python)" backend/app/modules/dental_3d` must find
  imports only inside `registration_infrastructure.py`.

## References

- `backend/app/modules/dental_3d/registration.py`
- `backend/app/modules/dental_3d/registration_infrastructure.py`
- `backend/app/modules/dental_3d/registration_service.py`
- `docs/technical/dental_3d/patient_registration.md`
