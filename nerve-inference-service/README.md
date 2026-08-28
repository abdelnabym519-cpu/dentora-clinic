# Dentora DentalSegmentator nerve-inference service

Optional infrastructure service implementing the Phase 5.2 `nerve-detection-v1`
HTTP boundary with DentalSegmentator / nnU-Net v2.2.1. It is not part of the
FastAPI backend process and never bundles model weights.

## Safety boundary

- Non-clinical clinical decision support only; dentist review remains required.
- Model weights are mounted read-only at runtime and are never committed.
- DICOM input must already be Dentora's allowlist-sanitized archive. This
  service revalidates the contract, digest, CT modality, reference UIDs and
  absence of common patient-identity/private tags before inference.
- Output points are native DICOM-patient LPS millimetres. No CBCT-to-IOS/face
  registration, tooth proximity, implant planning or surgical planning occurs.
- The returned `confidence` is the mean class-5 softmax over voxels predicted
  as mandibular canal in nnU-Net preprocessing space. It is not a calibrated
  probability, diagnostic accuracy or clinical-safety score.
- Production requests are blocked unless
  `DENTORA_NERVE_COMMERCIAL_USE_APPROVED=true`. This is an operational guard,
  not legal advice or a license determination.

## Expected model mount

Point `DENTORA_NERVE_MODEL_DIR` at the trained nnU-Net model folder containing:

```text
nnUNetTrainer__nnUNetPlans__3d_fullres/
  dataset.json
  plans.json
  fold_0/checkpoint_final.pth
```

DentalSegmentator weights are external artifacts. Do not copy them into this
repository or a Docker image.

## Endpoint

`POST /v1/nerve-detection`

Required headers:

- `Content-Type: application/zip`
- `X-Dentora-Contract: nerve-detection-v1`
- `X-Dentora-Input-Digest: sha256:<64 hex>`
- `Authorization: Bearer <token>` when `DENTORA_NERVE_SERVICE_TOKEN` is set.

The body is the deterministic de-identified ZIP produced by
`backend/app/modules/dental_3d/nerve_inference.py`.

Response shape is deliberately identical to the backend's strict Phase 5.2
service contract: `detected | no_detection | uncertain`, model provenance and
up to two left/right mandibular-canal polylines in millimetres. The polylines
are deterministic centerline approximations derived from connected components
of model label 5; they are not surgical trajectories or validated nerve
centerlines. By default no connected component is discarded (`min voxels = 1`);
more or fewer than two significant components makes the result `uncertain`.

## CPU development

The supplied image is CPU-only because the first verified Dentora development
machine has no NVIDIA CUDA device. Inference is serialized to one request at a
time to avoid concurrent memory spikes. A production GPU image can replace the
runtime without changing the Dentora application boundary.

## Local opt-in composition

Use the repository-root overlay together with the normal development stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.nerve-ai.yml up --build
```

Set `DENTORA_NERVE_MODEL_HOST_DIR` to the exact trained model folder before
starting the overlay. On Windows, forward-slash paths are the least ambiguous,
for example `C:/Dentora/Models/.../nnUNetTrainer__nnUNetPlans__3d_fullres`.

This overlay is intentionally not wired into the default client/production
Compose files. Production model licensing, HTTPS/service topology and compute
capacity require separate approval.

Official model record: https://zenodo.org/records/10829675

nnU-Net: https://github.com/MIC-DKFZ/nnUNet
