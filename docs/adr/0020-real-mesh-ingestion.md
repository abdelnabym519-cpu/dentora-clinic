# 0020 — Real mesh ingestion via geometry-source ports and media storage

- **Status:** accepted
- **Date:** 2026-08-23
- **Deciders:** Mohamed Abdelnaby (maintainer), Dentora core team
- **Tags:** dental-3d, modules, media, clean-architecture

## Context

Phase 1 (ADR 0018) shipped a synthetic, non-clinical 3D preview with a
deliberately source-agnostic scene contract. The governance gate
(ADR 0019) then made Clean Architecture a hard acceptance criterion:
before any real geometry enters dental_3d, the application layer must
depend on an inner-boundary **port**, never on parsers, storage or
providers. Real geometry also needs a home for its bytes; Dentora
already has exactly one file storage system — the media module
(documents, ownership, storage backends, archival, events).

## Decision

1. **`DentalGeometrySource` port** (`sources.py`, framework-free):
   sources return a `GeometryProvision` (teeth and/or mesh
   descriptors) for a clinic+patient pair. Adapters live in
   `infrastructure.py`: `SyntheticGeometrySource` (Phase 1 behaviour,
   unchanged — the regression-safe fallback) and
   `IntraoralScanGeometrySource` (discovers mesh documents in media).
   The composition root (`default_sources`) is infrastructure; the
   application imports it lazily at call time so the dependency
   direction stays inward.
2. **Media is the only storage path.** Uploads
   (`POST /dental_3d/patients/{id}/meshes`) are validated in pure
   `meshfiles.py` (extension + declared MIME + content sniff + size —
   STL and OBJ only, the minimum safe set) and stored via
   `media.DocumentService.create_document`. No second storage/upload
   abstraction, no filesystem writes from dental_3d, no duplicated
   ownership; the stored MIME is canonicalised
   (`model/stl`/`model/obj`) and doubles as the discovery vocabulary.
3. **Meshes are references, not payloads.** The scene carries
   `DentalMesh` descriptors (`document_id`, server-built `url`,
   display metadata); binary content is downloaded by the viewer
   through media's authorized route. No schema change: the isolated
   `dental_3d` Alembic branch still has one revision, and uninstall
   leaves scans as ordinary media documents.
4. **Viewer seam.** The frontend renders typed `SceneMeshRef`s
   (`lib/sceneMeshes.ts`, kind vocabulary `surface`/`tooth`/`nerve`/
   `implant`/…) — future segmented-tooth phases extend the vocabulary,
   not the viewer. Synthetic arch stays the loading/fallback state.
5. **Scope stays locked:** no AI segmentation, CBCT/DICOM, nerve
   detection, implant planning or clinical inference — those are later
   phases that will implement this same port with their own adapters.

## Consequences

### Good

- Application logic is provider-agnostic; swapping/adding geometry
  sources (segmentation, CBCT) touches `default_sources` only.
- Zero storage duplication; uploads inherit media's ownership model,
  size limits, events, archival and download authorization.
- Clinic isolation, RBAC and uninstall safety preserved; Phase 1
  behaviour and all its tests unchanged.
- Content sniffing blocks mislabeled/malicious files regardless of
  client-declared metadata.

### Bad / accepted trade-offs

- The scene `url` string couples to media's public download route
  (mirrored, not imported — media's URL helper is module-private).
- Application ingest calls media's `DocumentService` directly (the
  repo's sanctioned cross-module service pattern via
  `manifest.depends`); a narrower storage port can be extracted if
  dental_3d ever grows a second write path.
- `MAX_SCENE_MESHES = 8` caps discovery; larger archives need
  pagination or selection semantics later.

## Alternatives considered

- **Parse meshes server-side into vertices in the scene payload** —
  rejected: bloats payloads, duplicates three.js parsing, and pulls
  mesh parsing into the application layer.
- **A `dental_meshes` table in dental_3d** — rejected: duplicates
  media's ownership/archival model and needs a migration; references
  need no schema.
- **Extend media's public upload allowlist with mesh MIMEs** —
  rejected for now: widens every clinic's generic upload surface;
  dental_3d's endpoint validates mesh-specific rules instead.
- **Direct storage writes from dental_3d** — rejected: second storage
  system, explicitly forbidden.

## How to verify the rule still holds

- `grep -r "sqlalchemy\|fastapi" backend/app/modules/dental_3d/sources.py`
  → empty (port stays framework-free).
- `tests/modules/dental_3d/test_mesh_ingestion.py` — port/adapters,
  validation, RBAC, clinic isolation, archival, PUT hardening.
- `frontend/tests/dental3d/sceneMeshes.test.ts` — seam + fallback
  state machine; `frontend/tests/e2e/dental3d.spec.ts` — upload →
  render workflow.

## References

- `docs/adr/0018-dental-3d-foundation.md` — Phase 1 contract
- `docs/adr/0019-clean-architecture-standard.md` — governance gate
- `docs/technical/dental_3d/overview.md` — Phase 2 architecture
- `backend/app/modules/media/service.py` — `DocumentService`
