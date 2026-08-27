# Dental 3D — Automatic tooth segmentation (Phase 3)

Phase 3 foundation: automatic tooth segmentation as **non-clinical
decision support** behind a replaceable provider port, with an explicit
dentist-review workflow. Full rationale in
[ADR 0021](../../adr/0021-tooth-segmentation-foundation.md).

## Workflow (safety boundary)

```
Input (scene: tooth universe + mesh references)
   → Segmentation Analysis (provider via port)
   → Evidence / Confidence (per tooth, FDI)
   → Dentist Review (accept / reject, on the analysis row)
   → Dentist Decision (recorded; odontogram never mutated)
```

- No endpoint accepts a client-supplied segmentation result.
- `is_clinical` / `requires_review` are fixed literal types in the
  contracts — nothing can claim clinical status or skip review.
- A review records the dentist's acknowledgement of decision support;
  it never marks anything clinically completed and never writes to the
  odontogram.

## Architecture (ADR 0019 layers)

| Layer | File | Responsibility |
|---|---|---|
| Domain/port | `segmentation.py` | `ToothSegmentationProvider` protocol, `SegmentationRequest` / `SegmentationAnalysisResult` / `SegmentedTooth` / `SegmentationEvidence`, review payloads. Framework-free. |
| Application | `service.py` (`DentalSegmentationService`) | run / latest / review use cases; persistence; provider injection. |
| Infrastructure | `infrastructure.py` (`ArchPartitionSegmentationProvider`, `default_segmentation_provider`) | deterministic rule-based engine + composition root. |
| Persistence | `models.py` (`dental_segmentation_analyses`, migration `d3d_0002`) | append-only analyses + review state on the isolated dental_3d branch. |
| Presentation | `router.py`, `frontend/` | endpoints + card/viewer integration. |

## API

- `POST /api/v1/dental_3d/patients/{id}/segmentation` — run the
  provider server-side (`dental_3d.write`); returns the persisted
  analysis with `review_status="pending"`.
- `GET  /api/v1/dental_3d/patients/{id}/segmentation` — latest
  analysis (`dental_3d.read`); 404 when never run.
- `POST /api/v1/dental_3d/patients/{id}/segmentation/{analysis_id}/review`
  — dentist decision `{decision: accepted|rejected, note?}`
  (`dental_3d.write`); 409 when already reviewed.
- Scene `segmentation` summary (GET scene) mirrors the latest
  analysis: `status="completed"`, provider/method, counts, review
  state, `analysis_id` link, `non_clinical=true`.

## The deterministic engine (explicitly not a medical AI model)

`ArchPartitionSegmentationProvider` (`arch-partition`,
`deterministic-arch-partition-v0`): fixed rules, no randomness, no
environment reads (the server clock is passed in):

| Rule | Status | Confidence | Evidence basis |
|---|---|---|---|
| ToothRecord marks tooth absent | `missing` | 1.0 | `odontogram_record` |
| Present + restored condition (crown, implant, caries, …) | `uncertain` | 0.5 | `odontogram_record` |
| Present + healthy, scan meshes back the scene | `segmented` | 0.9 | `mesh_backed` (+ document ids) |
| Present + healthy, synthetic arch only | `segmented` | 0.75 / 0.7 deciduous | `arch_position` |

Confidence means *confidence in the status assignment*, never a
clinical probability. Bands for display: ≥0.8 high, ≥0.6 medium.

## Frontend

- `lib/segmentationView.ts` — pure projection (normalize, FDI join,
  confidence bands, uncertain list, overlay state); invalid teeth are
  dropped, never repaired; safety markers are fixed client-side too.
- `useDental3DSegmentation` (`composables/useDental3DScene.ts`) —
  latest/run/review actions; failures flip flags, never break the card.
- Card: status, counts, method + non-clinical label, uncertain FDI
  list, review actions (`dental_3d.write`), review state.
- Viewer: FDI label sprites (status-coloured, confidence-band dot)
  over the synthetic arch only; synthetic fallback, real mesh
  rendering, orbit/zoom/pan/resize/disposal untouched (labels join
  the `dental3d` group + disposables).

## Limitations & future work

- Per-tooth segmentation **meshes** (cut geometry) do not exist;
  `SceneMeshKind='tooth'` stays reserved (ADR 0020).
- Labels align to the synthetic arch positions — never to a real scan
  surface — until a real model provides per-tooth geometry.
- Analyses are derivable; uninstall drops the table with the module's
  Alembic branch.
- Replacing the engine: implement the port, change one line in
  `default_segmentation_provider`. Nothing else moves.
