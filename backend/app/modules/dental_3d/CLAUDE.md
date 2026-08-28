# dental_3d module

Dental 3D: 3D preview of a patient's dentition on the patient Summary.
Phase 1 established the source-agnostic scene contract with synthetic
demo geometry; Phase 2 adds **real mesh ingestion** — validated STL/OBJ
files stored through the media module and rendered by the viewer, with
the synthetic arch kept as the regression-safe fallback; Phase 3 adds
the **automatic tooth-segmentation foundation** — a deterministic,
explicitly non-clinical analysis behind a replaceable provider port,
with an enforced dentist-review workflow (ADR 0021); Phase 4 adds the
**mandibular nerve-detection foundation** — AI-assisted / simulated
canonical-model pathways with AI-estimated tooth proximities behind a
second replaceable port, same dentist-review boundary (ADR 0022);
Phase 5.1 adds the **CBCT/DICOM ingestion foundation** — validated CT
instances stored by media and grouped into normalized, non-diagnostic
series availability behind ports (ADR 0023). It does not decode pixels,
render volumes, detect anatomy/pathology or perform planning.
Phase 5.2 adds the production-ready **CBCT nerve-inference boundary**:
de-identified deterministic input archives, a replaceable HTTP engine,
structured native-coordinate outcomes and explicit model-unavailable failure.
The next phase adds **patient-specific rigid IOS→CBCT registration** behind
input/anatomy/registration ports: explicit mesh units, DentalSegmentator dental
anatomy, Open3D RANSAC + optional TEASER++ initialization + ICP, a validated
SE(3) transform, technical metrics and dentist review (ADR 0025). No trained
weights, clinical threshold, planning or new visualization ships here.

## Public API

- Routes mounted at `/api/v1/dental_3d/`.
- Key endpoints:
  - `GET    /dental_3d/patients/{patient_id}/scene` — geometry sources + persisted view state; permission `dental_3d.read`
  - `PUT    /dental_3d/patients/{patient_id}/scene` — full-replace per-tooth view state; permission `dental_3d.write`
  - `POST   /dental_3d/patients/{patient_id}/meshes` — ingest one STL/PLY/OBJ scan file (multipart); permission `dental_3d.write`
  - `POST   /dental_3d/patients/{patient_id}/cbct/dicom-instances` — validate/store one DICOM Part 10 CT instance and return normalized metadata; permission `dental_3d.write`
  - `POST   /dental_3d/patients/{patient_id}/segmentation` — run the segmentation provider server-side; permission `dental_3d.write`
  - `GET    /dental_3d/patients/{patient_id}/segmentation` — latest analysis (404 when never run); permission `dental_3d.read`
  - `POST   /dental_3d/patients/{patient_id}/segmentation/{analysis_id}/review` — dentist review decision; permission `dental_3d.write`
  - `POST   /dental_3d/patients/{patient_id}/nerve-detection` — run CBCT nerve inference (optional series UID); permission `dental_3d.write`
  - `GET    /dental_3d/patients/{patient_id}/nerve-detection` — latest nerve analysis (404 when never run); permission `dental_3d.read`
  - `POST   /dental_3d/patients/{patient_id}/nerve-detection/{analysis_id}/review` — dentist review decision; permission `dental_3d.write`
  - `POST   /dental_3d/patients/{patient_id}/alignment` — run patient-specific IOS→CBCT rigid registration; permission `dental_3d.write`
  - `GET    /dental_3d/patients/{patient_id}/alignment` — latest alignment result; permission `dental_3d.read`
  - `POST   /dental_3d/patients/{patient_id}/alignment/{alignment_id}/review` — dentist accept/reject; permission `dental_3d.write`

## Dependencies

`manifest.depends = ["patients", "odontogram", "media"]`. The
odontogram read is **read-only** (`ToothRecord` rows drive
presence/condition) with no FK towards odontogram tables. The media
integration is storage + discovery: uploads go through
`media.service.DocumentService.create_document` (the single storage
system), and scene meshes are references to media documents — no
binary in scene payloads, no second upload/storage abstraction, no
duplicate ownership (media owns clinic/patient linkage). CBCT instances
use the same path with canonical `application/dicom`; normalized series
metadata lives in media's existing `extra_data` extensibility field.

## Clean Architecture (ADR 0019 / ADR 0020)

- `schemas.py` — domain contracts (`DentalMesh`, `Tooth3D`,
  `DentalScene`, `SegmentationResult`) — Pydantic only.
- `sources.py` — the `DentalGeometrySource` **port** +
  `GeometryProvision` (framework-free inner layer).
- `cbct.py` — the `DicomIngestionPort`, normalized CT instance/series
  contracts and stable failure vocabulary (framework-free inner layer,
  ADR 0023). Identifying DICOM fields are deliberately absent.
- `cbct_service.py` — application orchestration over the injected DICOM
  ingestion port; no framework, parser or storage imports.
- `service.py` — application: scene assembly, merge, ingest use case.
  Depends on the port only; the default composition root
  (`infrastructure.default_sources`) is imported lazily at call time.
- `infrastructure.py` — adapters: `SyntheticGeometrySource` (Phase 1
  behaviour), `IntraoralScanGeometrySource` (media document discovery),
  `PydicomMediaCbctAdapter` (header parsing + media persistence),
  `CbctDicomGeometrySource` (normalized series discovery), and composition
  roots. pydicom/SQLAlchemy/media stay here.
- `meshfiles.py` — pure mesh validation (extension + MIME + content
  sniff; canonical MIME vocabulary drives discovery).
- `segmentation.py` — the `ToothSegmentationProvider` **port** +
  request/result/evidence contracts and the review payload
  (framework-free inner layer, ADR 0021). Safety flags are fixed
  literal types: results are always `is_clinical=False` and
  `requires_review=True`.
- `nerve.py` — the `NerveDetectionProvider` **port** + pathway /
  proximity / evidence contracts and the review payload (framework-free
  inner layer, ADR 0022). Same fixed safety literals; proximity
  warnings (`near`/`watch`/`none`) are display bands, never clinical
  verdicts.
- `nerve_inference.py` — Phase 5.2 infrastructure: clinic/patient-scoped
  media acquisition, DICOM de-identification and deterministic ordering,
  bounded HTTP inference adapter, strict output normalization and safe errors.
- `registration.py` — framework-free AlignmentResult, coordinate-frame, SE(3),
  provenance/metric/failure/review contracts and the three registration ports.
- `registration_service.py` — application orchestration and append-only
  persistence; imports concrete adapters lazily at the composition root.
- `registration_infrastructure.py` — media/DICOM acquisition,
  DentalSegmentator HTTP and Open3D/TEASER++/ICP adapters (ADR 0025).
- `router.py` / `tools.py` / `frontend/` — presentation.

## Permissions

`dental_3d.read`, `dental_3d.write`. Phase 5.1 adds no permission:
ingestion reuses write, while series availability rides the scene read.

Roles → permissions live in the manifest (admin/dentist `*`, hygienist
read+write, assistant read, receptionist none). Mesh **content** is
downloaded through the media module's own route, which additionally
requires `media.documents.read`.

## Tools exposed

| Tool | Category | Wraps | Permission |
|---|---|---|---|
| `get_patient_scene` | READ | `DentalSceneService.get_for_patient` | `dental_3d.read` |

## Events emitted

None.

## Events consumed

None directly. Ingested scans and DICOM instances trigger media's `DOCUMENT_UPLOADED`
(published by `DocumentService.create_document`); dental_3d discovers
mesh documents by query, not subscription — an event-driven refresh is
a future optimization, not a correctness need.

## Lifecycle

- `installable=True` / `auto_install=False` / `removable=True`.
- Phase 2 added no migration: meshes are media document references.
  Phase 3 adds `d3d_0002` on the same isolated `dental_3d` branch —
  the append-only `dental_segmentation_analyses` table (proposals +
  dentist review state). Phase 4 adds `d3d_0003` (`dental_nerve_analyses`,
  same shape: pathways + proximities + review state) — persisted because
  a review boundary that forgets itself on reload would be a boundary in
  name only. Phase 5.1 adds no migration. Phase 5.2 adds `d3d_0004`
  for explicit outcome/failure/provenance state. Uninstall drops only the
  dental_3d branch; uploaded scans/DICOM instances remain ordinary media
  documents owned by the media module, and
  analyses are derivable decision support. `d3d_0005` adds append-only
  `dental_alignment_results`; media inputs remain media-owned.

## Gotchas / non-obvious invariants

- Only documents stored with a **canonical mesh MIME**
  (`model/stl` / `model/obj`) surface as scene meshes — discovery is
  MIME-based, never extension- or title-based.
- Uploads accept `application/octet-stream` (browsers don't map
  `.stl`/`.obj`) but the stored document is always canonicalised to
  `model/stl` / `model/obj`.
- Binary STL validation is exact: `len(data) == 84 + 50·triangles`;
  ASCII STL must start with `solid` and contain `facet`.
- PLY registration input requires a bounded ASCII header with explicit format,
  vertices and faces. Its physical unit is still mandatory per alignment run.
- `DentalSceneUpdate` rejects tooth-level mesh descriptors (meshes are
  server-derived); scene-level `meshes` are never accepted from
  clients.
- Scene `generator` reports `intraoral_scan` whenever real meshes
  exist; the persisted row's `generator` stays `synthetic` (view-state
  provenance).
- `MAX_SCENE_MESHES = 8` caps discovery; raising it changes payload
  size, nothing else.
- DICOM ingestion accepts Part 10 CT only (`.dcm`/`.dicom`), reads a strict
  non-identifying header allowlist with `stop_before_pixels=True`, rejects
  DICOMDIR, and stores canonical MIME `application/dicom`.
- `cbct_series` means normalized data **availability**, not renderable
  geometry or a clinical result. It never changes the scene generator;
  synthetic fallback and existing viewer behavior remain intact.
- Discovery is bounded by `MAX_CBCT_INSTANCES = 2048` and
  `MAX_CBCT_SERIES = 32` per patient.
- Frontend: the viewer renders `SceneMeshRef[]` (`lib/sceneMeshes.ts`)
  — future mesh kinds (tooth/nerve/implant) extend `SceneMeshKind`, not
  the viewer architecture. A failed mesh load falls back to the
  synthetic arch + error chip.
- Segmentation is **non-clinical decision support**: the only write
  paths are "run the provider" and "record a review decision"; no
  endpoint accepts a client-supplied analysis, `PUT scene` still
  rejects `status="completed"`, and a review never mutates odontogram
  records. `ArchPartitionSegmentationProvider` is a rule-based
  foundation — never present it as a medical AI model.
- Production nerve detection is the Phase 5.2 CBCT adapter only. Missing
  model configuration is `failed/missing_model`; never substitute canonical
  anatomy. Model findings stay in DICOM patient coordinates and must not be
  overlaid on teeth/scans without an accepted patient-specific registration.
  No proximity, implant/surgical planning or clinical safety verdict is
  produced (ADR 0024).
- Segmentation analyses are append-only; latest wins in the scene
  summary. Re-reviewing a decided analysis is a 409.
- Viewer FDI labels render on the synthetic arch only — labelling a
  real scan surface would claim a per-tooth alignment the Phase 3
  engine does not have.
- Alignment always maps normalized IOS millimetres into the named DICOM patient
  frame. `CLINICAL_THRESHOLD_NOT_VALIDATED` is invariant; accepted review is
  an acknowledgement, not a clinical accuracy or treatment-planning claim.
