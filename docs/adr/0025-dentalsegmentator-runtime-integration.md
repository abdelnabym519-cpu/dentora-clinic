# 0025 — Integrate DentalSegmentator behind the nerve-inference boundary

- **Status:** accepted
- **Date:** 2026-08-24
- **Deciders:** Dentora Core Team
- **Tags:** dental-3d, ai, cbct, inference, deployment, licensing

## Context

ADR 0024 established an operator-controlled HTTP boundary for CBCT nerve
inference while deliberately leaving trained-model execution outside the Dentora
backend. That boundary preserves Clean Architecture: the application depends on
`NerveDetectionProvider`, infrastructure creates a de-identified deterministic
DICOM archive, and a replaceable service returns native DICOM-patient findings.

DentalSegmentator / nnU-Net v2.2 was then executed independently with the
published `Dataset112_DentalSegmentator_v100` checkpoint. On the official 3D
Slicer `PreDentalSurgery` CBCT sample, label 5 produced two mandibular-canal
components and the exported segmentation preserved the source image geometry.
The result was inspected in 2D and 3D in Slicer as an engineering plausibility
check. This is not clinical validation and does not establish a clinical
accuracy claim.

The model checkpoint and its commercial-use status remain external concerns.
Dentora must not bundle the weights or silently turn a research/development
model into a production dependency.

## Decision

Keep the ADR 0024 HTTP contract unchanged and add an **optional isolated
DentalSegmentator reference service** at the infrastructure edge. The Dentora
backend continues to know only the existing `nerve-detection-v1` HTTP contract;
PyTorch, nnU-Net, SimpleITK and model deserialization stay out of the backend
process.

The reference service:

- accepts only Dentora's bounded deterministic de-identified DICOM ZIP;
- revalidates the body digest, archive layout, CT modality, reference UIDs,
  absence of common identity/private tags and request size;
- mounts model weights read-only at runtime and never copies them into Git or a
  Docker image;
- runs `Dataset112_DentalSegmentator_v100`, fold 0,
  `checkpoint_final.pth`, with label 5 as mandibular canal;
- exports the nnU-Net segmentation back to the native DICOM volume geometry and
  rejects output whose size, spacing, origin or direction changed;
- converts label-5 connected components to deterministic polyline
  approximations in DICOM-patient LPS millimetres. They are display/review
  geometry, not surgical trajectories or validated nerve centerlines;
- derives service `confidence` from the model output as the mean class-5
  softmax over voxels predicted as label 5 in preprocessing space. The
  corresponding uncertainty is `1 - confidence`. This quantity is explicitly
  **not** a calibrated clinical probability, accuracy or safety score;
- serializes model execution to one request at a time so CPU development hosts
  do not amplify memory pressure;
- blocks production requests unless an operator explicitly sets
  `DENTORA_NERVE_COMMERCIAL_USE_APPROVED=true`. This flag is an operational
  deployment guard, not a legal determination that the checkpoint is cleared
  for commercial use.

The service is exposed only through an opt-in local Compose overlay. It is not
added to the default client or production Compose stacks while the commercial
license gate and production-resource design remain open. 3D Slicer remains a
development/validation tool and is not a Dentora client dependency.

## Consequences

### Good

- The proven Phase 5.2 application/domain contracts remain unchanged.
- Heavy ML dependencies and untrusted checkpoint deserialization remain in an
  isolated replaceable process.
- The backend can switch between CPU, future GPU, or another validated model
  service without changing application code.
- Native DICOM reference-space invariants are checked on both sides of the
  trust boundary.
- No model weight is committed or baked into a Dentora image.
- A production deployment fails closed until the commercial-use gate is
  explicitly satisfied.

### Bad / accepted trade-offs

- CPU inference is slow and memory intensive; the verified development run took
  about 20 minutes for one CBCT volume.
- The current Phase 5.2 contract stores polylines, so a deterministic
  approximation must be derived from the segmentation mask. A later phase may
  introduce a first-class volumetric mask artifact if the product needs it.
- Model-derived softmax confidence is uncalibrated and must never be presented
  as diagnostic accuracy.
- End-to-end Dentora DICOM-series execution still requires a separate gate;
  standalone model execution and the existing controlled HTTP adapter tests do
  not replace that integration test.
- Commercial-use clearance for the external model/weights remains unresolved.

## Alternatives considered

- **Embed nnU-Net/PyTorch in the Dentora backend** — rejected because it breaks
  the established infrastructure boundary, couples the application image to a
  large medical-ML runtime and increases the blast radius of weight loading.
- **Require 3D Slicer on every client** — rejected because Slicer is a
  validation/research tool here, not an application dependency, and would
  couple deployment to each workstation.
- **Commit or bake model weights** — rejected because weights are large,
  independently licensed artifacts and must stay operator-managed.
- **Return a fixed or invented confidence** — rejected because the Phase 5.2
  contract requires confidence and fabricated values would be misleading. The
  chosen value is explicitly derived from model logits and labeled
  uncalibrated.
- **Begin CBCT↔IOS/face registration now** — rejected as out of scope. Native
  DICOM findings must not be overlaid in another modality frame until a
  separately authorized registration phase.

## How to verify the rule still holds

- Run the lightweight tests under `nerve-inference-service/tests/`.
- Build the service image and verify `GET /health` reports the configured device
  and commercial-use gate state without loading the checkpoint.
- Run the existing backend
  `backend/tests/modules/dental_3d/test_nerve_inference.py` suite to verify the
  `nerve-detection-v1` contract, sanitization, failure mapping and DICOM native
  reference-space normalization.
- Confirm `git ls-files` contains no `.pth`, patient DICOM, NIfTI model output or
  model directory under `nerve-inference-service/`.
- For trained-model validation evidence and hashes, follow
  `docs/workflows/dental-3d-dentalsegmentator-validation.md` rather than
  repeating acquisition/inference work.

## References

- `docs/adr/0024-real-nerve-detection-boundary.md`
- `backend/app/modules/dental_3d/nerve_inference.py`
- `backend/app/modules/dental_3d/nerve.py`
- `nerve-inference-service/README.md`
- DentalSegmentator model record: https://zenodo.org/records/10829675
- nnU-Net: https://github.com/MIC-DKFZ/nnUNet
