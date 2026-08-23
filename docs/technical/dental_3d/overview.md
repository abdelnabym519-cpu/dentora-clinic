---
module: dental_3d
last_verified_commit: ec741ed
---

# dental_3d — technical overview

Dental 3D (Phase 2): a 3D preview of the patient's dentition on the
patient Summary — **real intraoral-scan meshes (STL/OBJ)** ingested
through the media module when available, with the Phase 1 synthetic,
non-clinical arch as the regression-safe fallback. The scene contract
stays source-agnostic so future real-geometry phases (tooth
segmentation, CBCT, 3D face scans, Digital Twin) plug into the same
`DentalGeometrySource` port. Optional and removable
(`installable=True`, `auto_install=False`, `removable=True`).

Module code lives at `backend/app/modules/dental_3d/`. Scope and
boundary rationale:
[`docs/adr/0018-dental-3d-foundation.md`](../../adr/0018-dental-3d-foundation.md)
(Phase 1) and
[`docs/adr/0020-real-mesh-ingestion.md`](../../adr/0020-real-mesh-ingestion.md)
(Phase 2).

## Architecture in 30 seconds

```
┌────────────────────────────┐   read-only    ┌──────────────────────┐
│ dental_scenes (dental_3d)  │ ◄── ToothRecord ─ tooth_records (odo) │
│ one row per patient        │    synthesis    └──────────────────────┘
└────────────────────────────┘
        │ per-tooth view state (JSONB: visible, color, mesh)
        ▼
┌──────────────────────────────────────────────────────────────────┐
│ GET/PUT /api/v1/dental_3d/patients/{id}/scene                    │
│ GET  = DentalGeometrySource provisions merged over persisted row │
│ PUT  = full-replace view state (upsert, unique per patient)      │
└──────────────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────┐
│ DentalGeometrySource port (sources.py — inner layer)             │
│  ├ SyntheticGeometrySource      (Phase 1 behaviour, unchanged)   │
│  └ IntraoralScanGeometrySource  ── references ──► media documents│
│ POST /patients/{id}/meshes = validated STL/OBJ → media storage   │
└──────────────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────┐
│ frontend layer: patient.summary.cards slot → Dental3DCard        │
│  └ <ClientOnly> Dental3DViewer (three.js, client plugin)         │
│     ├ lib/dentalArch.ts — pure FDI placement math (tested)       │
│     └ lib/sceneMeshes.ts — pure real-mesh seam (tested)         │
└──────────────────────────────────────────────────────────────────┘
```

Merge semantics on read: the odontogram always drives `condition` /
`present` (so recording a caries or extraction immediately changes the
3D scene); the persisted row only survives as view state (`visible`,
`color`, `mesh`). One clinical truth, one presentation preference.
Real meshes aggregate from every geometry source; while any exist the
scene reports `generator="intraoral_scan"` (the persisted row keeps
`synthetic` — view-state provenance).

## Phase 2 — real mesh ingestion

Flow: **real mesh → media storage → dental 3D → viewer**.

1. `POST /api/v1/dental_3d/patients/{id}/meshes` (multipart,
   `dental_3d.write`) — `DentalMeshService.ingest` validates the file
   in `meshfiles.py` (extension ∈ {`.stl`, `.obj`}; declared MIME must
   match; content sniff — binary STL must be exactly
   `84 + 50·triangles` bytes, ASCII STL starts with `solid` +
   `facet`, OBJ must decode as text with `v` and `f` records; size ≤
   `STORAGE_MAX_FILE_SIZE`) and stores it through the **media**
   module's `DocumentService.create_document` — the existing storage
   system, reusing media's ownership, backend, events and archival.
   The stored MIME is canonicalised to `model/stl` / `model/obj`;
   `application/octet-stream` uploads are accepted (browsers don't
   map mesh extensions) and canonicalised.
2. `IntraoralScanGeometrySource` discovers the patient's active mesh
   documents (canonical mesh MIME, clinic + patient scoped, newest
   first, capped at `MAX_SCENE_MESHES = 8`) and describes them as
   scene-level `DentalMesh` references (`document_id`, `url` pointing
   at media's authorized download route, label/size/uploaded_at). No
   binary ever enters the scene payload.
3. The viewer (`useDental3DMeshIO.fetchMeshContent`) downloads the
   mesh with the user's bearer token through media's download route
   (`media.documents.read`), parses it (`STLLoader`/`OBJLoader`) and
   normalizes it into the arch framing; the synthetic arch renders
   while loading and falls back on error.

No Phase 2 schema change: meshes are media document references, so the
isolated `dental_3d` Alembic branch still has a single revision and
uninstall leaves uploaded scans as ordinary media documents.

## Domain contract (deliberately minimal)

| Schema | Role |
|---|---|
| `DentalMesh` | Geometry descriptor — `source` (`synthetic` / `intraoral_scan` today; `segmentation`/`cbct`/`face_scan`/`digital_twin` reserved), `format` (`procedural` / `stl` / `obj`; `gltf` reserved), `document_id` referencing the media document for real meshes, `vertex_count`, display metadata (`label`, `file_size`, `uploaded_at`) and the server-built content `url`. |
| `Tooth3D` | One tooth: FDI number (validated against the odontogram `ALL_TEETH` universe), `present`, `condition`, `color` override (`#RRGGBB`), `visible`, `mesh`. |
| `DentalScene` | Aggregate: `generator` + `teeth` (≤52 = FDI universe) + `segmentation` + `meshes` (server-derived real mesh references). |
| `SegmentationResult` | Placeholder for automatic tooth segmentation. Phase 2 always answers `status="not_available"`; `DentalSceneUpdate` rejects `completed` (future capability, not client-suppliable). |

No parallel tooth/treatment model exists here — FDI identity and
clinical state belong to the odontogram (ADR 0018). No parallel media
system either — files belong to the media module (ADR 0020).

## API surface

Routes mounted at `/api/v1/dental_3d/`.

| Verb | Path | Permission |
|------|------|------------|
| GET | `/patients/{patient_id}/scene` | `dental_3d.read` |
| PUT | `/patients/{patient_id}/scene` | `dental_3d.write` |
| POST | `/patients/{patient_id}/meshes` | `dental_3d.write` |

Unknown or cross-clinic patient → 404 (same `_ensure_patient` pattern
as the odontogram/periodontogram routers). Invalid FDI numbers, a
`completed` segmentation payload or a client-supplied tooth-level mesh
descriptor → 422. Invalid mesh uploads (bad extension/MIME/content,
oversized) → 400 with a stable code prefix
(`unsupported_extension` / `mime_mismatch` / `malformed_stl` /
`malformed_obj` / `empty_file` / `too_large`).

## Frontend layer

- Slot: `patient.summary.cards` (order 50, gated on `dental_3d.read`)
  registered by `frontend/plugins/slots.client.ts` — same contract as
  the odontogram's DiagnosesCard.
- `Dental3DViewer.vue` — client-only three.js viewer (OrbitControls:
  rotate/zoom/pan; ResizeObserver; full resource disposal). Loaded via
  `defineAsyncComponent` from the `.client.ts` plugin and additionally
  wrapped in `<ClientOnly>`; falls back to a message when WebGL is
  unavailable. Renders real surface meshes (STL/OBJ loaders, centered
  + scaled into the arch framing) with loading / error / badge overlay
  states; a failed scan load falls back to the synthetic arch.
- `lib/dentalArch.ts` — dependency-free placement math (quadrant
  mirroring, parabolic arch curve, per-category scaling). Unit-tested
  in `frontend/tests/dental3d/`.
- `lib/sceneMeshes.ts` — the real-mesh seam: maps scene mesh
  references to typed `SceneMeshRef`s (kind vocabulary `surface` /
  `tooth` / `nerve` / `implant` / …) and owns the pure loading/error/
  fallback state machine. Future segmented-tooth phases extend the
  kind vocabulary, not the viewer architecture. Unit-tested.
- Synthetic geometry is isolated inside the viewer's
  `buildToothMeshes`; real geometry inside `buildSurfaceMesh`.
- `Dental3DCard.vue` also offers an STL/OBJ upload control
  (`dental_3d.write` holders only) that ingests via the module API and
  refreshes the scene.
- Locales: en / es / fr / pt / ar under `frontend/i18n/locales/`.

## Scope lock (Phases 1–2)

No AI inference, tooth segmentation, nerve detection, implant
planning, pathology detection, CBCT/DICOM processing, multimodal
fusion, face-scan processing, Digital Twin intelligence, diagnosis or
clinical prediction. The synthetic geometry carries **no clinical
accuracy claim** and the UI shows that disclaimer permanently.
