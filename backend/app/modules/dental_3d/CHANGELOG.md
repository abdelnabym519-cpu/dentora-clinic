# Changelog — dental_3d module

## Unreleased

### Phase 5.2 runtime integration — DentalSegmentator reference service

- Added an optional isolated `nerve-inference-service/` implementing the
  existing `nerve-detection-v1` HTTP boundary with DentalSegmentator / nnU-Net;
  the `NerveDetectionProvider`, application service, API and persistence
  contracts remain unchanged (ADR 0025).
- Model weights remain external read-only artifacts and are never bundled with
  Dentora or committed. The default/client/production stacks remain unchanged;
  local integration is opt-in through `docker-compose.nerve-ai.yml`.
- The service revalidates Dentora's de-identified DICOM archive, preserves
  native DICOM-patient geometry, derives label-5 mandibular-canal polylines and
  returns model-derived but explicitly uncalibrated confidence/uncertainty.
- Standalone execution of the published Dataset112 checkpoint on the public 3D
  Slicer `PreDentalSurgery` CBCT sample was verified with native geometry and
  bilateral label-5 output. This is engineering validation only, not clinical
  validation or an accuracy claim; the commercial-use gate remains open.
- Completed the real Dentora DICOM-service end-to-end integration through the
  sanitized HTTP boundary into DentalSegmentator and back into persisted
  native-coordinate findings: bilateral `dicom_patient` pathways were detected,
  preserved for dentist review and accepted by the frontend contract without
  inventing tooth proximity or overlaying unregistered DICOM geometry on the
  synthetic arch. Dental3D-specific TypeScript validation is clean; this remains
  engineering validation only and the commercial-use gate remains open.

- Closed the Phase 5.2 E2E contract gap: seeded patients without a
  validated CBCT series now validate the intended fail-safe path
  (`failed` / `invalid_input`, zero findings/proximity, no dentist review)
  instead of the retired Phase 4 canonical demo output. The patient card
  also no longer presents a non-reviewable failed operation as a rejected
  dentist verification.

### 0.5.0 — Phase 5.1: CBCT/DICOM ingestion foundation

- Framework-independent `DicomIngestionPort`, normalized CT instance/series
  contracts, fixed non-diagnostic markers and stable validation errors
  (`cbct.py`); port-only application orchestration (`cbct_service.py`).
- Replaceable `PydicomMediaCbctAdapter`: DICOM Part 10 CT header validation
  with a strict tag allowlist and no Pixel Data decoding. pydicom is pinned to
  the 3.0.2 security floor and isolated in infrastructure (ADR 0023).
- Existing media storage only: raw DICOM instances are clinic/patient-owned
  `Document` rows (`application/dicom`); normalized non-identifying metadata
  uses the existing `extra_data` field. No new table or migration.
- `CbctDicomGeometrySource` joins the preserved synthetic/intraoral source
  composition and exposes grouped `cbct_series` availability in scene reads
  without treating it as renderable or patient-aligned geometry.
- Minimal `POST /patients/{id}/cbct/dicom-instances` endpoint behind
  `dental_3d.write`; clinic isolation, cross-clinic 404 behavior, media
  download authorization and archival semantics are reused.
- No frontend, diagnosis, clinical nerve detection, patient-specific nerve
  alignment, pathology detection, implant or surgical planning was added.

### 0.4.0 — Phase 4: mandibular nerve detection foundation

- `NerveDetectionProvider` port (`nerve.py`, framework-free inner
  layer): provider identity, `input_kind`, request (scene tooth
  universe + mesh references + server clock), typed pathway contracts
  (side left/right, region, polyline points in the canonical arch
  frame, status detected/uncertain, confidence 0–1, evidence with
  source `canonical_demo_model`) and per-tooth proximity contracts
  (FDI, side, distance mm, closest vertex, warning band near/watch/
  none). Safety flags are fixed literal types — results are always
  `is_clinical=False`, `requires_review=True`; warnings are display
  bands for "AI-estimated proximity", never clinical safety verdicts.
- Deterministic adapter `CanonicalMandibleNerveProvider`
  (`infrastructure.py`): canonical mandibular-canal model —
  **AI-assisted / simulated, not a clinically validated detector, not
  patient-specific anatomy** — with the composition root
  `default_nerve_provider` as the single future CBCT/ML swap point
  (ADR 0022).
- Persistence: append-only `dental_nerve_analyses` (migration
  `d3d_0003`, isolated dental_3d branch) with dentist review state;
  persisted because the review boundary must survive reloads. Uninstall
  drops it with the branch; no second tooth/patient model.
- API: `POST/GET /patients/{id}/nerve-detection` and
  `POST /patients/{id}/nerve-detection/{analysis_id}/review`; scene
  summary mirrors the latest analysis (`nerve_detection`: status/
  provider/counts/review state, `non_clinical=true`). No endpoint
  accepts client-supplied results (`PUT scene` rejects
  `nerve_detection.status="completed"`); reviews never approve an
  implant/surgical plan or mutate odontogram data.
- Frontend: `lib/nerveView.ts` (pure projection + FDI join +
  confidence bands + overlay gating), `useDental3DNerveDetection`
  composable, nerve tube overlay in `Dental3DViewer` (synthetic arch
  only, toggleable, disposed with the scene) and a review section in
  `Dental3DCard` with fixed "AI-assisted / simulated — requires
  dentist verification" wording; i18n for en/es/fr/pt/ar.
- ThreeUI evaluated per the phase authorization: not present in the
  repository; existing Three.js implementation preserved (ADR 0022 §8).
- Tests: backend domain/service/API suites; frontend nerveView +
  composable suites; e2e workflow + RBAC spec.


### 0.3.0 — Phase 3: automatic tooth segmentation foundation

- `ToothSegmentationProvider` port (`segmentation.py`, framework-free
  inner layer): provider identity, `input_kind`, request (scene tooth
  universe + mesh references + server clock), per-tooth result (FDI,
  status segmented/uncertain/missing, confidence 0–1, evidence),
  mandated determinism. Safety flags are fixed literal types — results
  are always `is_clinical=False`, `requires_review=True`.
- Deterministic adapter `ArchPartitionSegmentationProvider`
  (`infrastructure.py`): rule-based
  arch-partition analysis — **not a medical AI model** — with the
  composition root `default_segmentation_provider` as the single
  future ML swap point (ADR 0021).
- Persistence: append-only `dental_segmentation_analyses` (migration
  `d3d_0002`, isolated dental_3d branch) with dentist review state
  (pending → accepted/rejected + reviewer + note). Uninstall drops it
  with the branch; no second tooth/patient model — FDI identity stays
  odontogram-owned.
- API: `POST/GET /patients/{id}/segmentation` and
  `POST /patients/{id}/segmentation/{analysis_id}/review`; scene
  summary now mirrors the latest analysis (status/provider/counts/
  review state/`analysis_id`, `non_clinical=true`). No endpoint
  accepts client-supplied results; review never mutates odontogram
  data.
- Frontend: `lib/segmentationView.ts` (pure projection + FDI join +
  confidence bands + overlay state), `useDental3DSegmentation`
  composable, card segmentation section (status, counts, method with
  non-clinical label, uncertain FDI list, review actions for
  `dental_3d.write`), viewer FDI label sprites over the synthetic arch
  only; locales en/es/fr/pt/ar.
- Tests: `test_segmentation_domain.py` (contracts, determinism, FDI
  mapping, invalid results, purity), `test_segmentation_service.py`
  (persistence, review workflow, isolation, provider seam),
  `test_segmentation_api.py` (RBAC, isolation, HTTP boundary),
  `segmentationView.test.ts`, `useDental3DSegmentation.test.ts`,
  `dental3d_segmentation.spec.ts` (e2e workflow + RBAC).
- Docs: ADR 0021, `docs/technical/dental_3d/segmentation.md`.
- Module version 0.3.0.

### 0.2.0 — Phase 2: real mesh ingestion (released in 6dbeada)

- Phase 2 — real mesh ingestion: `DentalGeometrySource` port
  (`sources.py`) with `SyntheticGeometrySource` (Phase 1 behaviour
  unchanged) and `IntraoralScanGeometrySource` (discovers mesh
  documents from the media module) behind it; `DentalMeshService.ingest`
  validates STL/OBJ (extension + MIME + content sniff + size) and
  stores through `media.DocumentService` — no second storage system,
  no schema change, meshes are document references.
- API: `POST /api/v1/dental_3d/patients/{id}/meshes` behind
  `dental_3d.write`; scene responses now carry server-derived `meshes`
  (+ label/file_size/uploaded_at/url) and report
  `generator="intraoral_scan"` when real geometry exists. `PUT` rejects
  client-supplied tooth-level mesh descriptors.
- Frontend: viewer renders real STL/OBJ geometry (three.js loaders,
  authorized media download) with loading/error overlay states and the
  synthetic arch as fallback; card gains scan upload (write-permission
  gated), mesh count and scan disclaimer; locales en/es/fr/pt/ar.
- `manifest.depends` now includes `media` (auto-installed,
  non-removable); module version 0.2.0.

## Phase 1


- Phase 1 foundation: `DentalScene` persistence (one row per patient,
  isolated `dental_3d` Alembic branch) with per-tooth view state
  (visibility, colour override) merged over odontogram-driven
  presence/condition on read.
- Domain contracts `DentalMesh` / `Tooth3D` / `DentalScene` /
  `SegmentationResult` (source-agnostic, Phase 1 answers
  `synthetic` / `not_available` only).
- API: `GET`/`PUT /api/v1/dental_3d/patients/{id}/scene` behind
  `dental_3d.read` / `dental_3d.write`.
- Agent tool `get_patient_scene` (READ) wrapping the service.
- Frontend layer: `patient.summary.cards` slot card with a client-only
  three.js viewer rendering synthetic arch geometry; locales en/es/fr/
  pt/ar.
