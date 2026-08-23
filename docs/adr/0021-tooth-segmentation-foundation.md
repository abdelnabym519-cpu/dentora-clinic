# ADR 0021: Automatic tooth segmentation foundation behind a provider port

- Status: accepted
- Date: 2026-08-23
- Phase: 3
- Depends on: [ADR 0018](0018-dental-3d-foundation.md), [ADR 0019](0019-clean-architecture-standard.md), [ADR 0020](0020-real-mesh-ingestion.md)

## Context

Phases 1–2 deliver a 3D dentition scene: synthetic geometry driven by
odontogram `ToothRecord` state (ADR 0018) plus real STL/OBJ scan
ingestion through media (ADR 0020). Phase 3 adds **automatic tooth
segmentation** — detecting/representing individual teeth on the 3D
scene, associated with FDI notation, with confidence and evidence.

Two hard truths shape the decision:

1. **No validated segmentation model exists in the repository.** Adding
   a heavyweight ML framework to fake intelligence would violate the
   dependency discipline ADR 0019 exists to protect and would mislabel
   a demo as a medical capability.
2. **Segmentation is decision support, never a decision.** The clinical
   workflow stays: Input → Segmentation Analysis → Evidence /
   Confidence → **Dentist Review** → **Dentist Decision**. No result is
   a diagnosis; no output is clinically complete until a dentist says
   so — and even then, review records an acknowledgement, never an
   odontogram mutation.

## Decision

1. **Port, not engine.** Segmentation is an external capability behind
   the `ToothSegmentationProvider` protocol (`segmentation.py`, inner
   layer, framework-free): provider identity (`name`), supported input
   (`input_kind`), `SegmentationRequest` (the patient's scene: tooth
   universe + mesh references + server clock), `SegmentationAnalysisResult`
   (per-tooth `SegmentedTooth` output: FDI number, status, confidence
   0–1, `SegmentationEvidence`), and mandated determinism. The
   application service (`DentalSegmentationService`) depends on the
   port only; adapters and the composition root
   (`default_segmentation_provider`) live in `infrastructure.py`.
2. **Deterministic Phase 3 adapter.** `ArchPartitionSegmentationProvider`
   is an explicitly rule-based analysis — **not a medical AI model** —
   documented as such everywhere it surfaces (API disclaimer, UI,
   docs). Rules are fixed and random-free: odontogram-absent teeth are
   `missing` (confidence 1.0 in the status); restored teeth
   (crown/implant/caries/…) are `uncertain` (0.5) because restorations
   alter observable geometry; healthy teeth are `segmented`
   (0.9 scan-backed / 0.75 synthetic / 0.7 deciduous).
3. **Safety encoded in the contracts.** `is_clinical` is the literal
   type `False` and `requires_review` the literal `True` on results and
   responses — no provider can state otherwise. Client-supplied
   segmentation results are impossible: the only write paths are
   "run the provider" and "record a review decision" (`accepted` /
   `rejected`); scene-level `PUT` still rejects `status="completed"`.
4. **Persistence = append-only analyses + review state.**
   `dental_segmentation_analyses` (same isolated `dental_3d` Alembic
   branch, `d3d_0002`): provider, method, teeth JSONB (FDI-validated,
   confidence-bounded by Pydantic), `review_status` pending →
   accepted/rejected, reviewer, note. Latest analysis wins in the scene
   summary; history is kept. Uninstall drops the table with the branch
   — analyses are derivable decision support, not source clinical data.
5. **No second tooth model.** Tooth identity stays FDI + odontogram
   `ToothRecord`; the provider *reads* that universe via the scene's
   tooth list and never creates parallel tooth/patient data.
6. **UI shows the workflow, honestly.** The summary card surfaces
   status (not run / pending review / accepted / rejected), counts,
   method with the non-clinical label, uncertain FDI numbers, and
   Accept/Reject for `dental_3d.write` holders. The viewer draws FDI
   label sprites over the **synthetic arch only** — labelling a real
   scan surface per-tooth would claim an alignment the deterministic
   foundation does not have; that arrives with a real model.

## Future ML integration seam

Replacing the engine means implementing `ToothSegmentationProvider`
(analyzing scan mesh content, or another `input_kind`) and swapping
one line in `default_segmentation_provider`. Contracts, service,
persistence, review workflow, UI and tests are untouched. Confidence
bands (≥0.8 high, ≥0.6 medium) are mirrored front-side for display.

## Consequences

- The full pipeline (run → evidence → review → decision) is exercisable
  and tested end-to-end today with deterministic outputs.
- Real mesh ingestion and the synthetic fallback are unchanged;
  segmentation is purely additive at every layer.
- Per-tooth segmentation *meshes* (cut geometry) remain future work —
  `SceneMeshKind` already reserves the `'tooth'` kind; no code path
  may set it yet (ADR 0020 discipline).
- The deterministic confidences are honest artifacts of documented
  rules; they must never be quoted as clinical accuracy.
