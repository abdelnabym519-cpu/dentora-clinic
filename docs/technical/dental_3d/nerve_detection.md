# dental_3d — CBCT nerve detection (Phase 5.2 + reference runtime)

Status: production architecture implemented; standalone trained-model execution
verified; Dentora DICOM-service end-to-end gate pending · ADRs:
[0024](../../adr/0024-real-nerve-detection-boundary.md),
[0025](../../adr/0025-dentalsegmentator-runtime-integration.md)

Phase 5.2 replaces the Phase 4 canonical demo as the production provider with a
bounded CBCT inference-service adapter. An unconfigured deployment returns and
persists `failed / missing_model`; it never emits hard-coded anatomy as a
detection.

ADR 0025 adds an optional isolated DentalSegmentator reference service that
implements the already-established HTTP contract. The backend remains free of
PyTorch, nnU-Net and model weights. The reference service is opt-in for local
integration work and is not part of the default client/production stack while
the commercial-use and production-resource gates remain open.

## Architecture

| Responsibility | Implementation | Layer |
|---|---|---|
| Outcomes, geometry, provenance, uncertainty, provider port | `nerve.py` | inner boundary |
| Run/latest/review orchestration | `service.py` | application |
| DICOM acquisition, de-identification, archive, HTTP engine | `nerve_inference.py` | infrastructure |
| Production composition root | `infrastructure.default_nerve_provider` | infrastructure |
| Optional DentalSegmentator runtime | `nerve-inference-service/` | isolated infrastructure service |
| API | `router.py` | interface |
| Native/canonical display projection | `frontend/lib/nerveView.ts` | interface |

The existing `NerveDetectionProvider` seam is retained. Domain/application
code imports no pydicom, storage, SQLAlchemy, HTTP, model runtime, NumPy,
PyTorch, ONNX, CUDA or Three.js.

## Backend pipeline

1. Select the requested (or newest) patient-owned `CbctSeriesDescriptor`.
2. Re-query every media document by document id, clinic id, patient id,
   active status and canonical DICOM MIME.
3. Parse each Part 10 instance and rebuild it from an allowlist containing
   pixel data plus geometry/intensity tags. Patient identity, free text and
   private tags are excluded.
4. Sort slices by the normal derived from Image Orientation/Position Patient,
   with SOP Instance UID as a deterministic fallback.
5. Build a deterministic, uncompressed ZIP with fixed timestamps, a bounded
   manifest and SHA-256 input digest.
6. POST it to the operator-configured inference service using the
   `nerve-detection-v1` contract. Redirects and environment proxies are
   disabled; request/response sizes and time are bounded.
7. Validate the response strictly and normalize findings into DICOM patient
   coordinates (millimetres + Frame of Reference UID).

Configuration:

- `DENTAL_3D_NERVE_INFERENCE_URL` (empty means `missing_model`; HTTPS required
  in production)
- `DENTAL_3D_NERVE_INFERENCE_TOKEN`
- `DENTAL_3D_NERVE_INFERENCE_TIMEOUT_SECONDS`
- `DENTAL_3D_NERVE_MAX_INSTANCES`
- `DENTAL_3D_NERVE_MAX_INPUT_BYTES`
- `DENTAL_3D_NERVE_LOW_CONFIDENCE_THRESHOLD`

## Optional DentalSegmentator service

`nerve-inference-service/` accepts the deterministic backend ZIP and runs
DentalSegmentator `Dataset112_DentalSegmentator_v100` behind the same HTTP
contract. Model weights are mounted read-only and never committed or baked into
the service image.

The service revalidates the body digest, archive layout, CT modality and DICOM
reference UIDs. Inference output must preserve the native source size, spacing,
origin and direction. Label 5 is split into 26-connected components and
converted to deterministic polyline approximations in DICOM-patient LPS
millimetres. These polylines are review/display geometry, not validated nerve
centerlines or surgical trajectories.

Because Phase 5.2 requires a confidence value while raw DentalSegmentator
segmentation does not publish a calibrated case confidence, the service derives
a transparent model signal: mean class-5 softmax over voxels predicted as label
5 in nnU-Net preprocessing space. `1 - confidence` is returned as model-reported
uncertainty with an explicit note that the number is not a calibrated clinical
probability, accuracy or safety score. No fixed confidence is invented.

For CPU development, inference is serialized to one request at a time. The
local Compose overlay raises the backend model-service timeout to 2400 seconds;
the base backend timeout remains unchanged.

Service-only configuration:

- `DENTORA_NERVE_MODEL_HOST_DIR` — host folder mounted read-only at
  `/models/model` by the local overlay
- `DENTORA_NERVE_SERVICE_TOKEN`
- `DENTORA_NERVE_DEVICE` (`cpu` by default)
- `DENTORA_NERVE_CPU_THREADS`
- `DENTORA_NERVE_MAX_REQUEST_BYTES`
- `DENTORA_NERVE_MIN_COMPONENT_VOXELS` (default `1`; no component-size
  suppression unless an operator explicitly changes it)
- `DENTORA_NERVE_COMMERCIAL_USE_APPROVED` (default `false`)

Production requests are rejected by the reference service while
`DENTORA_NERVE_COMMERCIAL_USE_APPROVED=false`. This is a fail-closed deployment
guard, not a statement that setting the flag establishes legal or regulatory
clearance.

## API and outcomes

`POST /api/v1/dental_3d/patients/{id}/nerve-detection` optionally accepts
`{"series_instance_uid": "..."}`. The structured result distinguishes:

- `detected`: one or more validated findings;
- `uncertain`: service-reported uncertainty, confidence below the configured
  threshold, or a component pattern that is not the expected bilateral pair;
- `no_detection`: inference completed without a finding (still reviewable);
- `failed`: invalid input, unsupported modality, missing model, initialization,
  inference, malformed output or invalid geometry failure.

Each model finding has a stable id, side/region, native reference space,
polyline, confidence, reported-or-not-reported uncertainty and backing media
document ids. Operation metadata includes model id/version, adapter id, input
digest, Study/Series/Frame UIDs, duration and a confidence summary. No raw model
output or infrastructure exception reaches the API.

## Safety and visualization

- All anatomy output is non-clinical decision support and requires dentist
  review. Operational failures contain no anatomy and use `not_applicable`
  review state.
- Native DICOM findings are surfaced to the UI but deliberately not overlaid
  on the synthetic arch or an intraoral scan. That requires the separately
  authorized patient-specific alignment phase.
- Phase 5.2/reference-runtime integration produces no tooth
  distance/proximity, safety recommendation, implant position, surgical
  trajectory, pathology result or treatment plan.
- Historical Phase 4 rows remain parseable, but the canonical provider is no
  longer present in production wiring.
- 3D Slicer is used only for development/validation and is not required on a
  Dentora client workstation.

## Model status

DentalSegmentator/nnU-Net has now been executed outside the Dentora backend
with the published `Dataset112_DentalSegmentator_v100` checkpoint on the
public 3D Slicer `PreDentalSurgery` CBCT sample. The run produced 5,856 label-5
voxels in two bilateral connected components and preserved native geometry;
2D/3D inspection passed an engineering anatomical-plausibility check. Exact
hashes, versions and re-run conditions are recorded in
`docs/workflows/dental-3d-dentalsegmentator-validation.md`.

This evidence does **not** constitute clinical validation or a
mandibular-canal-specific accuracy claim. Commercial-use clearance for the
external model/weights is not established by this repository and remains a
separate production gate.

The next integration gate is an end-to-end Dentora DICOM-series run through the
sanitized HTTP boundary into the isolated model service and back into persisted
native-coordinate findings.
