# Changelog — dental_3d module

## Unreleased

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
