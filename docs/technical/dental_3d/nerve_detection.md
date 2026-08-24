# dental_3d — CBCT nerve detection (Phase 5.2)

Status: production architecture implemented; trained model integration not
verified · ADR: [0024](../../adr/0024-real-nerve-detection-boundary.md)

Phase 5.2 replaces the Phase 4 canonical demo as the production provider with
a bounded CBCT inference-service adapter. Dentora does not ship model weights
or a medical-model runtime. An unconfigured deployment returns and persists
`failed / missing_model`; it never emits hard-coded anatomy as a detection.

## Architecture

| Responsibility | Implementation | Layer |
|---|---|---|
| Outcomes, geometry, provenance, uncertainty, provider port | `nerve.py` | inner boundary |
| Run/latest/review orchestration | `service.py` | application |
| DICOM acquisition, de-identification, archive, HTTP engine | `nerve_inference.py` | infrastructure |
| Production composition root | `infrastructure.default_nerve_provider` | infrastructure |
| API | `router.py` | interface |
| Native/canonical display projection | `frontend/lib/nerveView.ts` | interface |

The existing `NerveDetectionProvider` seam is retained. Domain/application
code imports no pydicom, storage, SQLAlchemy, HTTP, model runtime, NumPy,
PyTorch, ONNX, CUDA or Three.js.

## Pipeline

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

## API and outcomes

`POST /api/v1/dental_3d/patients/{id}/nerve-detection` optionally accepts
`{"series_instance_uid": "..."}`. The structured result distinguishes:

- `detected`: one or more validated findings;
- `uncertain`: service-reported uncertainty or confidence below the configured
  threshold;
- `no_detection`: inference completed without a finding (still reviewable);
- `failed`: invalid input, unsupported modality, missing model, initialization,
  inference, malformed output or invalid geometry failure.

Each model finding has a stable id, side/region, native reference space,
polyline, confidence, reported-or-not-reported uncertainty and backing media
document ids. Operation metadata includes model id/version, adapter id, input
digest, Study/Series/Frame UIDs, duration and a confidence summary. No raw
model output or infrastructure exception reaches the API.

## Safety and visualization

- All anatomy output is non-clinical decision support and requires dentist
  review. Operational failures contain no anatomy and use `not_applicable`
  review state.
- Native DICOM findings are surfaced to the UI but deliberately not overlaid
  on the synthetic arch or an intraoral scan. That would require the
  patient-specific alignment explicitly deferred to Phase 5.3.
- Phase 5.2 produces no tooth distance/proximity, safety recommendation,
  implant position, surgical trajectory, pathology result or treatment plan.
- Historical Phase 4 rows remain parseable, but the canonical provider is no
  longer present in production wiring.

## Model status

No trained nerve model or inference-capable medical runtime exists in this
repository. DentalSegmentator/nnU-Net was evaluated as an external candidate,
but its large weights/runtime and clinical/resource trust boundary are not
silently bundled. Therefore the adapter and full normalized pipeline are
tested with a controlled HTTP contract, while execution of an actual trained
model remains an explicit deployment/integration gap.
