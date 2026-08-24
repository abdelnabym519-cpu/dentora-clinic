# Dental 3D — DentalSegmentator validation record

Status: engineering validation complete for the standalone sample pipeline;
Dentora DICOM-service end-to-end gate pending.

This record exists so agents do **not** repeat expensive model acquisition,
checkpoint inspection or CPU inference unless a later change invalidates one of
the recorded inputs.

## Scope and safety

- Model: DentalSegmentator / nnU-Net v2.2, dataset 112.
- Intended Dentora use: non-clinical decision support with dentist review.
- Test data: official public 3D Slicer `CBCTDentalSurgery` sample; no real
  patient data was used.
- Result: engineering/runtime and anatomical-plausibility evidence only.
- Not established: clinical validation, diagnostic accuracy, regulatory
  clearance, commercial-use clearance, CBCT↔IOS/face registration, implant or
  surgical planning.
- Never describe the published overall multiclass result as "94% nerve
  accuracy"; it is not a mandibular-canal-specific accuracy figure.

## Reproducibility anchors

### Model archive

- Source: https://zenodo.org/records/10829675
- Archive: `Dataset112_DentalSegmentator_v100.zip`
- Published/verified MD5:
  `b71cd5230168d28a4f71b078265b76be`
- Local checkpoint size: `247050939` bytes.
- Local checkpoint SHA-256:
  `A3A91AE0F8D7AB403D8662E47D2F0BDF7FC51E7783B46632841274DFF8266C32`
- Model weights are external local artifacts and must not be committed.

Verified dataset contract:

- channel `0`: `CT`
- label `1`: Upper Skull
- label `2`: Mandible
- label `3`: Upper Teeth
- label `4`: Lower Teeth
- label `5`: Mandibular canal
- file ending: `.nii.gz`
- configuration: `3d_fullres`
- image reader/writer: `SimpleITKIO`
- target spacing:
  `(0.43164101243019104, 0.31200000643730164, 0.43164101243019104)`
- patch size: `(128, 160, 112)`
- normalization: `CTNormalization`

### CBCT sample

- Sample: 3D Slicer `CBCTDentalSurgery` / `PreDentalSurgery.gipl.gz`.
- Verified source SHA-256:
  `7BFA16945629C319A439F414CFB7EDDDD2A97BA97753E12EEDE3B56A0EB09968`
- Size: `24,774,961` bytes.
- Source geometry:
  - size `(360, 360, 330)`
  - spacing `(0.5, 0.5, 0.5)` mm
  - origin `(0, 0, 0)`
  - identity direction
  - signed 16-bit pixels.

The GIPL source was converted to an nnU-Net input named
`PreDentalSurgery_0000.nii.gz` using SimpleITK without resampling. Size,
spacing, origin, direction, pixel type and sampled physical corner coordinates
matched before and after conversion.

## Verified runtime

CPU-only development image:

- Python 3.10
- nnU-Net `2.2.1`
- PyTorch `2.2.2+cpu`
- NumPy `1.26.4`
- CUDA unavailable/disabled
- 12 CPU threads for the successful inference path.

The checkpoint initialized successfully with:

- trainer: `nnUNetTrainer`
- configuration: `nnUNetPlans_3d_fullres`
- one input channel
- fold `0`
- `30,789,214` network parameters.

Preprocessing produced tensor shape `(1, 361, 503, 417)` float32 with finite
values, no NaN/Inf and non-zero intensity variation.

The standard CLI multiprocessing path exhausted the available worker-memory
budget on the development host. The successful validation used the same
nnU-Net preprocessor, predictor and official export function in one Python
process to remove only multiprocessing orchestration; model logic and weights
were unchanged.

## Standalone inference result

- Sliding-window tiles: `210 / 210`.
- Approximate prediction duration: `20m 06s` on CPU.
- Logits shape: `(6, 361, 503, 417)`, float16.
- Native output geometry matched input exactly.
- Output label inventory:
  - background: `41,459,852`
  - Upper Skull: `912,943`
  - Mandible: `266,228`
  - Upper Teeth: `67,161`
  - Lower Teeth: `55,960`
  - Mandibular canal: `5,856`.

Label 5 had exactly two 26-connected components:

| Component | Voxels | Volume (mm³) | Centroid (LPS mm) |
|---|---:|---:|---|
| 1 | 2,964 | 370.5 | `(58.289, 83.572, 37.570)` |
| 2 | 2,892 | 361.5 | `(122.114, 85.010, 36.205)` |

The label-5 visualization mask retained all `5,856` voxels and native geometry.
3D Slicer 5.12.3 was used to inspect CBCT slices plus a 3D view with the
mandible semi-transparent and the two canal components visible within it. The
result passed an **engineering anatomical-plausibility** check; this is not
clinical validation.

## Integration interpretation

The standalone evidence proves:

`CBCT sample → DentalSegmentator/nnU-Net → patient-specific label-5 mask → native geometry`

It does **not** yet prove the full Dentora deployed path:

`Dentora DICOM upload → sanitized nerve-detection-v1 archive → isolated service → native LPS polyline response → persistence/API`

The latter is the next end-to-end gate. The existing backend adapter tests
already verify deterministic de-identification, slice ordering, strict HTTP
normalization, native reference-space contracts and safe failure outcomes with a
controlled service response.

## Re-run conditions

Do not repeat the expensive standalone inference merely for review. Re-run it
only if one of these changes:

- checkpoint bytes or model dataset/configuration;
- nnU-Net/PyTorch inference version or prediction settings;
- GIPL/NIfTI conversion logic or image geometry handling;
- label-5 postprocessing logic in a way that needs a new mask baseline;
- CPU/GPU runtime implementation whose numerical equivalence must be checked.

The model/commercial-license gate remains open. Production use requires a
separate documented approval; the repository does not infer that approval from
this technical result.
