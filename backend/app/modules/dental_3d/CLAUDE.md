# dental_3d module

Dental 3D: 3D preview of a patient's dentition on the patient Summary.
Phase 1 established the source-agnostic scene contract with synthetic
demo geometry; Phase 2 adds **real mesh ingestion** — validated STL/OBJ
files stored through the media module and rendered by the viewer, with
the synthetic arch kept as the regression-safe fallback.

## Public API

- Routes mounted at `/api/v1/dental_3d/`.
- Key endpoints:
  - `GET    /dental_3d/patients/{patient_id}/scene` — geometry sources + persisted view state; permission `dental_3d.read`
  - `PUT    /dental_3d/patients/{patient_id}/scene` — full-replace per-tooth view state; permission `dental_3d.write`
  - `POST   /dental_3d/patients/{patient_id}/meshes` — ingest one STL/OBJ scan file (multipart); permission `dental_3d.write`

## Dependencies

`manifest.depends = ["patients", "odontogram", "media"]`. The
odontogram read is **read-only** (`ToothRecord` rows drive
presence/condition) with no FK towards odontogram tables. The media
integration is storage + discovery: uploads go through
`media.service.DocumentService.create_document` (the single storage
system), and scene meshes are references to media documents — no
binary in scene payloads, no second upload/storage abstraction, no
duplicate ownership (media owns clinic/patient linkage).

## Clean Architecture (ADR 0019 / ADR 0020)

- `schemas.py` — domain contracts (`DentalMesh`, `Tooth3D`,
  `DentalScene`, `SegmentationResult`) — Pydantic only.
- `sources.py` — the `DentalGeometrySource` **port** +
  `GeometryProvision` (framework-free inner layer).
- `service.py` — application: scene assembly, merge, ingest use case.
  Depends on the port only; the default composition root
  (`infrastructure.default_sources`) is imported lazily at call time.
- `infrastructure.py` — adapters: `SyntheticGeometrySource` (Phase 1
  behaviour), `IntraoralScanGeometrySource` (media document discovery),
  `default_sources` composition root.
- `meshfiles.py` — pure mesh validation (extension + MIME + content
  sniff; canonical MIME vocabulary drives discovery).
- `router.py` / `tools.py` / `frontend/` — presentation.

## Permissions

`dental_3d.read`, `dental_3d.write`.

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

None directly. Ingested scans trigger media's `DOCUMENT_UPLOADED`
(published by `DocumentService.create_document`); dental_3d discovers
mesh documents by query, not subscription — an event-driven refresh is
a future optimization, not a correctness need.

## Lifecycle

- `installable=True` / `auto_install=False` / `removable=True`.
- No Phase 2 migration: meshes are media document references, so the
  `dental_scenes` table (isolated `dental_3d` Alembic branch) is
  unchanged. Uninstall drops only the dental_3d branch; uploaded scans
  remain ordinary media documents owned by the media module.

## Gotchas / non-obvious invariants

- Only documents stored with a **canonical mesh MIME**
  (`model/stl` / `model/obj`) surface as scene meshes — discovery is
  MIME-based, never extension- or title-based.
- Uploads accept `application/octet-stream` (browsers don't map
  `.stl`/`.obj`) but the stored document is always canonicalised to
  `model/stl` / `model/obj`.
- Binary STL validation is exact: `len(data) == 84 + 50·triangles`;
  ASCII STL must start with `solid` and contain `facet`.
- `DentalSceneUpdate` rejects tooth-level mesh descriptors (meshes are
  server-derived); scene-level `meshes` are never accepted from
  clients.
- Scene `generator` reports `intraoral_scan` whenever real meshes
  exist; the persisted row's `generator` stays `synthetic` (view-state
  provenance).
- `MAX_SCENE_MESHES = 8` caps discovery; raising it changes payload
  size, nothing else.
- Frontend: the viewer renders `SceneMeshRef[]` (`lib/sceneMeshes.ts`)
  — future mesh kinds (tooth/nerve/implant) extend `SceneMeshKind`, not
  the viewer architecture. A failed mesh load falls back to the
  synthetic arch + error chip.
