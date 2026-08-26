# ADR 0022: Mandibular nerve detection foundation behind a provider port

- Status: accepted
- Date: 2026-08-24
- Phase: dental_3d Phase 4
- Supersedes: none (extends ADR 0019 / ADR 0020 / ADR 0021)

## Context

dental_3d can already render a patient's 3D dentition (synthetic arch
fallback, real STL/OBJ ingestion — ADR 0020) and produce per-tooth
segmentation proposals with dentist review (ADR 0021). Phase 4 adds the
next planning-support capability: representing and visualizing a
mandibular nerve pathway and its relationship to dental anatomy.

There is **no validated nerve-detection model in the repository** and no
CBCT pipeline (explicitly out of scope). Any "detection" we could ship
today would be a canonical anatomical model, not patient-measured
anatomy. The clinical stakes are high (nerve involvement drives implant
and surgical decisions), so the safety boundary must be as much a part
of the contract as the geometry.

## Decision

1. **Port, not engine.** Nerve detection is an external capability
   behind the `NerveDetectionProvider` protocol
   (`app/modules/dental_3d/nerve.py`), exactly mirroring the Phase 3
   segmentation port. The application service
   (`DentalNerveService`) depends on the port only; the composition
   root (`default_nerve_provider` in `infrastructure.py`) installs the
   engine. Swapping in a real CBCT/ML detector later implements the
   protocol and changes nothing else.

2. **Deterministic canonical adapter for Phase 4.**
   `CanonicalMandibleNerveProvider` ("canonical-mandible") derives
   left/right mandibular-canal polylines from documented constants in
   the *same canonical arch frame as the synthetic dentition*
   (`frontend/lib/dentalArch.ts`: half-width 2.2, depth 1.5, gap 0.5;
   millimetre scale 10 units→mm, documented, **not a calibration**).
   It computes AI-estimated proximities from lower-tooth root-apex
   anchors to the pathway polyline. No randomness, no environment
   reads, clock injected. It is explicitly labelled a demo anatomical
   model (`source: canonical_demo_model`) — **never a clinically
   validated detector and never patient-specific anatomy**.

3. **Structured pathway data, not a UI line.** A pathway is a typed
   contract: side (left/right), region (`mandibular_canal`), polyline
   points in the arch frame, status (`detected`/`uncertain`),
   confidence (0–1), evidence (basis/note/backing documents), source.
   Proximities are separate typed records: FDI tooth, side, distance
   in mm, closest polyline vertex, warning band (`near`/`watch`/
   `none`), confidence.

4. **Safety boundary encoded in the schema.** `is_clinical` is
   `Literal[False]` and `requires_review` is `Literal[True]` — no
   provider can claim otherwise. Warning bands are display bands for
   "AI-estimated proximity"; **no tooth is ever labelled clinically
   unsafe, and no implant or surgical plan is created or approved.**
   The UI wording is fixed: "AI-assisted / simulated nerve detection",
   "requires dentist verification".

5. **Workflow.** Input → nerve analysis → evidence/confidence →
   dentist review → dentist decision. Only the server runs the
   provider; there is no endpoint that accepts a client-supplied
   detection (PUT scene rejects `nerve_detection.status="completed"`).
   Reviews are terminal per analysis (409 on re-review) and never
   mutate odontogram records.

6. **Persistence.** A dedicated `dental_nerve_analyses` table
   (migration `d3d_0003`, same append-only + review-state shape as
   Phase 3's `d3d_0002`) on the module's isolated Alembic branch.
   A table is genuinely required: a review boundary that forgets
   itself on reload would be a boundary in name only. FKs stay within
   core (clinics/patients/users) — no cross-module FKs, uninstall
   isolation preserved.

7. **3D integration.** The pathway renders as a tube overlay in the
   existing `Dental3DViewer` (Three.js), positioned in the synthetic
   arch frame, toggleable, disposed with the scene. It renders **only
   while the synthetic arch renders**: overlaying a canonical pathway
   on a real patient scan would pretend an alignment nobody has. The
   `'nerve'` `MeshSource`/`SceneMeshKind` vocabulary is reserved for a
   future mesh-export path; Phase 4 pathways are analysis output, not
   downloadable documents.

8. **ThreeUI decision.** The authorization asked to evaluate ThreeUI.
   Inspection found **no ThreeUI package, API, or integration anywhere
   in the repository** (only `three` ^0.185.1). Inventing an external
   UI library API is out of scope, so the existing clean Three.js
   implementation is preserved. If ThreeUI is introduced later it must
   stay at this same presentation edge — never in the
   `NerveDetectionProvider` contract, segmentation contracts, or any
   business rule.

## Confidence and evidence semantics

- Pathway confidence 0.6 / status `uncertain` when the scene has no
  real geometry at all (purely generic model), 0.75 / `detected` when
  scan meshes back the arch frame — capped below the "high" band
  (0.8) because even then the pathway itself is canonical, not a
  patient canal.
- Evidence basis is always `anatomical_model`; backing scan documents
  are listed. The evidence explains what the model looked at — never
  proof of clinical correctness.

## Future CBCT/ML integration seam

`NerveDetectionProvider.detect(request) -> NerveDetectionResult` is the
entire seam. A future adapter (CBCT volume in, patient-specific canal
out) implements the protocol and is returned by
`default_nerve_provider()`; contracts, persistence, review workflow,
scene summary and UI are untouched. New input kinds (e.g. CBCT volumes)
extend the `NerveDetectionInputKind` literal, never the port shape.

## Consequences

- The full nerve workflow (contracts → persistence → review → 3D
  overlay → RBAC) is exercisable end-to-end today with deterministic
  output, ready for a real detector behind the same port.
- Every payload and every UI surface repeats the same truth: simulated,
  non-clinical, requires dentist verification.
- Distances are model-space estimates against demo anatomy — useful
  for UI/planning-support plumbing, meaningless as clinical
  measurements until a real detector ships.
- Phase 5+ (per authorization): pathology detection, implant planning,
  CBCT processing, etc. remain explicitly out of scope.
