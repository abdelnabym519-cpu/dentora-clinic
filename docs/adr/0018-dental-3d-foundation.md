# 0018. Dental 3D foundation as a removable synthetic-geometry module

Date: 2026-08-23

## Status

Accepted

## Context

Dentora's roadmap includes 3D capabilities (automatic tooth
segmentation, nerve detection, AI implant planning, CBCT
visualization, intraoral scan + 3D face scan integration, Dental
Digital Twin, multimodal fusion). None of them can ship in one piece:
they need mesh ingestion, AI inference infrastructure, heavy storage
and clinical validation.

What every one of them *does* need on day one is:

- a persistent, clinic-scoped place to describe "the 3D scene of this
  patient's dentition";
- an API + UI surface where 3D content appears without forking the
  odontogram or the patient architecture;
- a rendering pipeline (camera, lights, controls, disposal) that
  real geometry can later flow through.

Two integration options existed: extend the odontogram module in
place, or add a new removable module.

## Decision

1. **New module `dental_3d`** (`depends = ["patients", "odontogram"]`,
   `removable=True`, `auto_install=False`) — the odontogram stays the
   single clinical truth for teeth; the 3D module is a presentation
   layer that can be uninstalled without touching it. Cross-module
   access is read-only on `ToothRecord` with **no FK** towards
   odontogram tables, so uninstall safety (ADR 0002 branch isolation)
   holds.

2. **Minimal source-agnostic contract**: `DentalMesh` (provenance:
   `synthetic` today; `segmentation` / `cbct` / `intraoral_scan` /
   `face_scan` / `digital_twin` reserved), `Tooth3D` (FDI reference,
   view state), `DentalScene` (aggregate, ≤ the 52-tooth FDI universe),
   `SegmentationResult` (placeholder that Phase 1 always answers
   `not_available`). Future phases swap the geometry *source*; the API
   shape does not change.

3. **Merge semantics**: on read, presence/condition are always
   re-derived from the odontogram; the persisted row carries only view
   state (visibility, colour override). One clinical truth, one
   presentation preference — no second tooth model.

4. **UI through the slot registry**: the card registers into
   `patient.summary.cards` (same contract as the odontogram's
   DiagnosesCard), gated on `dental_3d.read`. No odontogram code is
   modified.

5. **Synthetic geometry only** (scope lock): the Phase 1 viewer
   renders procedural demo shapes with a permanent "not clinical data"
   disclaimer. No AI inference, segmentation, CBCT/DICOM processing,
   or clinical claims. Three.js is the only new dependency (client-only
   layer code, disposed on unmount).

## Consequences

- Real-mesh phases land as new `DentalMesh.source` values + media-module
  scan storage references (`document_id`), not as schema breaks.
- Segmentation results can never be client-supplied — the update schema
  rejects `status="completed"` until the capability exists.
- The module adds one table (`dental_scenes`) on its own Alembic
  branch `dental_3d`.
- Receptionists never see the card (no permission grant), matching the
  periodontogram boundary.
