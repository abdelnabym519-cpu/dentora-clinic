# dental_3d — Mandibular nerve detection (Phase 4)

Status: accepted · ADR: [0022](../../adr/0022-nerve-detection-foundation.md) · Module: `backend/app/modules/dental_3d`

AI-assisted / simulated nerve detection for the 3D scene: canonical
left/right mandibular-canal pathways plus per-tooth AI-estimated
proximities, persisted behind a dentist-review boundary. **Non-clinical
decision support — a dentist must verify everything this phase
produces.**

## Architecture

| Piece | File | Layer |
|---|---|---|
| Port + contracts (`NerveDetectionProvider`, pathways, proximities) | `nerve.py` | inner boundary (pydantic contracts only) |
| Application use cases (run / latest / review) | `service.py` → `DentalNerveService` | application |
| Deterministic adapter (`CanonicalMandibleNerveProvider`) + composition root | `infrastructure.py` | infrastructure |
| HTTP endpoints | `router.py` | presentation (API) |
| Persistence | `models.py` → `dental_nerve_analyses`, migration `d3d_0003` | infrastructure |
| View projection (pure) | `frontend/lib/nerveView.ts` | presentation (pure) |
| Fetch/run/review composable | `frontend/composables/useDental3DScene.ts` | presentation |
| 3D tube overlay + toggle | `frontend/components/Dental3DViewer.vue`, `Dental3DCard.vue` | presentation (Three.js) |

Dependency direction is one-way (presentation → application → port ←
infrastructure), mirroring Phase 3's segmentation seam exactly.

## API

All under `/api/v1/dental_3d`, clinic-scoped, patient-authorized:

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/patients/{id}/nerve-detection` | `dental_3d.write` | Run the analysis server-side (201, review `pending`) |
| GET | `/patients/{id}/nerve-detection` | `dental_3d.read` | Latest analysis (404 when never run) |
| POST | `/patients/{id}/nerve-detection/{analysis_id}/review` | `dental_3d.write` | Dentist decision `accepted`/`rejected` (409 on re-review) |

`GET /patients/{id}/scene` carries a server-derived
`nerve_detection` summary (status, provider, counts, review state,
`non_clinical: true`). `PUT .../scene` rejects any client-supplied
`nerve_detection.status == "completed"` payload (422) — there is no
path by which a client result presents itself as completed.

## The canonical model (Phase 4 engine)

`CanonicalMandibleNerveProvider` — deterministic, no randomness, no
environment reads, clock injected via the request:

- **Pathways**: one per side (left/right), a 6-point polyline in the
  canonical arch frame (the same frame as `frontend/lib/dentalArch.ts`
  — half-width 2.2, depth 1.5, gap 0.5; scale 10 units ≈ mm,
  documented, not a calibration).
- **Status/confidence**: `uncertain` / 0.6 with no real geometry;
  `detected` / 0.75 when scan meshes back the arch frame (capped below
  the 0.8 "high" band — the pathway is canonical either way).
  Evidence basis is always `anatomical_model`; backing scan documents
  are listed.
- **Proximities**: present permanent lower teeth only (FDI 31–48);
  distance = minimum point-to-polyline distance from the tooth's
  root-apex anchor × the mm scale; teeth farther than 15 mm are
  omitted. Bands: `< 2 mm near`, `< 5 mm watch`, else `none` — display
  bands for "AI-estimated proximity", **never clinical safety
  verdicts**.
- Typical full-arch output: 2 pathways, proximities for all 16 lower
  teeth — near: 37/38/47/48, watch: 34/35/36/44/45/46, none:
  31/32/33/41/42/43.

## Safety boundary

- `is_clinical` is `Literal[False]`, `requires_review` is
  `Literal[True]` — fixed in the schema, not flags.
- Workflow: Input → Nerve analysis → Evidence/Confidence → Dentist
  review → Dentist decision. Reviews are terminal (409) and never
  approve an implant/surgical plan or touch odontogram data.
- UI wording is fixed across locales: "AI-assisted / simulated nerve
  detection", "requires dentist verification", "AI-estimated proximity,
  not a safety verdict".

## 3D rendering rules

- Pathways render as `THREE.TubeGeometry` tubes (colour by confidence
  band, half-opacity when `uncertain`) in the synthetic arch frame,
  with a visibility toggle; geometry/materials join the viewer's
  disposal lifecycle.
- **Synthetic arch only**: the canonical frame has no relationship to
  a patient's real scan surface, so the overlay is hidden while a real
  mesh renders (same policy as segmentation labels).
- The `'nerve'` `MeshSource`/`SceneMeshKind` value reserves the mesh
  vocabulary for a future export path; Phase 4 pathways are analysis
  output, not downloadable documents.

## ThreeUI decision

ThreeUI was evaluated per the phase authorization: **it does not exist
in the repository** (no package, no API, no integration — only `three`
^0.185.1). The existing Three.js implementation is preserved; any
future ThreeUI adoption must stay at this presentation edge and out of
the ports/contracts/business rules. See ADR 0022 §8.

## Limitations

- The engine is a demo anatomical model — distances are model-space
  estimates, not clinical measurements; no patient-specific canal
  exists until a real detector ships.
- No CBCT input, no volumetric analysis, no implant/surgical planning
  (Phase 5+ scope, needs its own authorization).
- Left/right coverage is the permanent mandibular dentition only.

## Future CBCT/ML integration seam

Implement `NerveDetectionProvider.detect()` (a future CBCT input kind
extends `NerveDetectionInputKind`, never the port shape) and return it
from `default_nerve_provider()` — contracts, persistence, review
workflow, scene summary and UI are untouched (ADR 0022).
