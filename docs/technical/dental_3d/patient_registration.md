# Patient-specific IOS → CBCT rigid registration

This capability computes a real rigid SE(3) transform from an uploaded
intraoral scan (STL, PLY or OBJ) into the selected patient's DICOM coordinate
frame. It uses patient geometry only. It does not generate canonical arches,
invent landmarks, apply arbitrary offsets or use non-rigid deformation.

## Runtime architecture

```text
patient-owned IOS + validated CBCT media
  → MediaRegistrationInputAdapter (ownership, units, frame, de-identification)
  → DentalAnatomyPort / operator DentalSegmentator service
  → RegistrationPort / Open3DRigidRegistrationAdapter
  → global candidates (Open3D RANSAC, TEASER++ when bindings are available)
  → measured candidate selection
  → iterative Open3D point-to-plane ICP
  → AlignmentResult persistence, API and dentist review
```

DentalSegmentator, Open3D and TEASER++ do not enter the domain or application
layers. PyTorch, nnU-Net, model weights and 3D Slicer are not Dentora backend
dependencies. The DentalSegmentator deployment is an operator-managed service
that returns dental-surface points in `DICOM_PATIENT_LPS` millimetres and the
same Frame of Reference UID as its request.

## Data and coordinate safety

- The run request must specify `mesh_document_id`, `series_instance_uid` and
  `ios_units` (`mm`, `cm`, `m` or `inch`). STL/PLY/OBJ have no trustworthy unit
  standard, so there is deliberately no default.
- The IOS document and every CBCT instance are queried with both `clinic_id`
  and `patient_id`. Archived or cross-clinic media are not inputs.
- CBCT requires consistent Study/Series/Frame of Reference UIDs, dimensions,
  positive pixel spacing, slice thickness, image position and orientation.
- The DentalSegmentator request archive contains a fixed DICOM allowlist and
  Pixel Data. Identifying and private tags are excluded, instances are ordered
  geometrically, and the archive is deterministic and SHA-256 addressed.
- DentalSegmentator output is rejected unless it declares DICOM patient LPS,
  millimetres and the exact requested Frame of Reference UID.
- Meshes are sniffed again after storage retrieval. Empty, malformed,
  non-finite or degenerate geometry is rejected.
- The persisted 4×4 matrix maps normalized IOS millimetres into DICOM patient
  millimetres. Domain validation enforces a homogeneous bottom row,
  orthonormal rotation and determinant `+1` (no scale/reflection).

## Registration and metrics

Open3D performs deterministic voxel downsampling, normal estimation and FPFH
feature extraction. Open3D RANSAC always supplies a global candidate. When the
optional TEASER++ Python bindings are installed and at least three mutual FPFH
correspondences exist, TEASER++ supplies an outlier-resistant candidate. Each
candidate is refined with one-iteration ICP steps; the implementation measures
transform/RMSE change to record convergence. The selected result is the
candidate with the greatest measured ICP fitness, then lowest ICP RMSE.

`AlignmentResult.metrics` records initializer, point counts, feature and inlier
correspondence counts, global/ICP fitness, global/ICP RMSE in millimetres,
overlap ratio, ICP iterations/convergence and outlier ratio. These are
engineering measurements, not a diagnosis or treatment threshold. Every result
contains:

```text
clinical_threshold_status = CLINICAL_THRESHOLD_NOT_VALIDATED
```

A converged transform starts `pending_review`; a finite transform without
technical ICP convergence starts `uncertain`. A dentist may set either to
`accepted` or `rejected`. Operational failures are `failed`, contain no
transform and cannot be reviewed. Acceptance acknowledges technical review; it
does not make the result clinically validated or approve treatment.

## API

All routes are clinic/patient scoped under `/api/v1/dental_3d`:

| Verb | Path | Permission |
|---|---|---|
| POST | `/patients/{patient_id}/alignment` | `dental_3d.write` |
| GET | `/patients/{patient_id}/alignment` | `dental_3d.read` |
| POST | `/patients/{patient_id}/alignment/{alignment_id}/review` | `dental_3d.write` |

Runs are append-only. The GET endpoint returns the latest result. Review is a
single transition from `pending_review`/`uncertain` to `accepted`/`rejected`.

## Configuration

`DENTAL_3D_DENTAL_SEGMENTATOR_URL` is empty by default, producing an explicit
`dependency_unavailable` failure. Production requires HTTPS. The token,
timeout, archive limits, voxel size, global distance, ICP distance and ICP
iteration limit are operator settings documented in `.env.example`.

## Commercial-use license gate

Checked 2026-08-25 against authoritative project metadata:

| Component | Runtime status | License | Gate |
|---|---|---|---|
| [Open3D](https://github.com/isl-org/Open3D/blob/main/LICENSE) | Python dependency `>=0.19,<0.20` (`open3d-cpu` on Linux, `open3d` elsewhere) | MIT | PASS — commercial use permitted; retain notice. |
| [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) | Direct Python dependency `>=1.26,<3` | BSD-3-Clause (wheel notices may include compatible bundled licenses) | PASS — retain notices. |
| [TEASER++](https://github.com/MIT-SPARK/TEASER-plusplus/blob/master/LICENSE) | Optional system-built Python binding; RANSAC remains available without it | MIT | PASS — commercial use permitted; retain notice. |
| [SlicerDentalSegmentator code](https://github.com/gaudot/SlicerDentalSegmentator/blob/main/LICENSE.txt) | External service/reference; not bundled | Apache-2.0 | PASS — commercial use permitted with license/notice obligations. |
| [DentalSegmentator weights](https://zenodo.org/records/10829675) | Operator-managed external asset; not downloaded or redistributed by Dentora | CC BY 4.0 in Zenodo record metadata | PASS with attribution — deployment must preserve model/version and required attribution. |

No training dataset or other model is introduced. A deployment using different
weights must independently verify and record their license and provenance.

## Known limitations

- No clinical acceptance threshold has been validated.
- Quality depends on IOS coverage, CBCT acquisition and DentalSegmentator
  output; the API preserves metrics and review state rather than claiming
  accuracy.
- TEASER++ Python wheels are not a portable PyPI dependency; operators may
  install the upstream MIT-licensed bindings. The adapter measures and chooses
  between available global candidates.
- The phase does not add non-rigid registration, CBCT/face registration,
  pathology detection, implant/surgical planning, or a new ThreeUI/AI
  visualization. The transform is available through the API for a separately
  authorized projection phase.
