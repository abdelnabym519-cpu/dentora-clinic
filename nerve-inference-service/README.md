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

## Model provenance & license (verified)

| Field | Value |
|---|---|
| Model | DentalSegmentator — nnU-Net v2, dataset **Dataset112_DentalSegmentator_v100** (470 CT/CBCT scans, 5 anatomical classes incl. mandibular canal = label 5) |
| Source | Zenodo record **10829675** (DOI `10.5281/zenodo.10829674` concept), file `Dataset112_DentalSegmentator_v100.zip` |
| Checksum | zip md5 **`b71cd5230168d28a4f71b078265b76be`** (record metadata; re-verified by `scripts/provision_model.py` at download time) |
| Weights license | **CC BY 4.0** — commercial use permitted **with attribution**. Verified against the Zenodo record metadata and independent integration audits (CBCTer `LICENSING.md`, TotalSegmentatorWrapper notes); consistent with `docs/technical/dental_3d/patient_registration.md` |
| Code license | SlicerDentalSegmentator / nnU-Net v2: Apache-2.0 (service implementation in this repo is original) |
| Attribution | Dot G, et al. DentalSegmentator: robust open source deep learning-based CT and CBCT image segmentation. *Journal of Dentistry* (2024). doi:10.1016/j.jdent.2024.105130 |
| Provisioning | `python nerve-inference-service/scripts/provision_model.py --target <dir>` (download + md5 verify + extract + identity validate + sha256 manifest; idempotent) |

Do **not** use the GitHub release asset `Dataset111_453CT_v100.zip` — it is
the earlier teeth-only model; the runtime contract (dataset.json label
`Mandibular canal` == 5) rejects it. Runtime memory note from upstream: full
CBCT nnU-Net inference is memory-hungry (upstream recommends 32 GB RAM;
16 GB machines may need a swap file on Linux/WSL). CPU execution is the
designed default here (`DENTORA_NERVE_DEVICE=cpu`, torch CPU wheel pinned in
the Dockerfile); expect slow-but-working inference on CPU.

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
