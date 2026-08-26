# Implant Planning — deterministic prosthetic-guided patient-space foundation

Implant Planning is engineering decision support. It does not autonomously choose or approve an implant, does not define clinical safety margins, and does not convert research results into clinical claims. A dentist must review every prosthetic target and every implant draft/proposal before clinical acceptance.

## Coordinate and geometry contract

All persisted planning geometry uses `dicom_patient` coordinates in millimetres. An implant candidate stores its center point, normalized platform-to-apex axis, diameter and length. A prosthetic target stores its intended implant-platform center and axis in the same patient frame. ThreeUI may project those values for display, but renderer coordinates are never persisted back as clinical coordinates.

The planning case reuses accepted patient-space inputs already owned by Dentora: the accepted IOS→CBCT registration, accepted real mandibular-nerve pathways in the same DICOM Frame of Reference, explicit prosthetic information, and validated anatomy artifacts when they exist. Frame-mismatched, rejected, stale or provenance-free geometry is not consumed.

## Prosthetic target and IOS contract

`ProstheticTarget` / `ProstheticPlanning` are first-class Implant Planning contracts, not a decorative viewer option. A target contains:

- an explicit implant-platform center in `dicom_patient/mm`;
- an explicit normalized platform-to-apex axis;
- the DICOM Frame of Reference UID;
- source type and method;
- source identifier, optional/required digest as appropriate, source document IDs and accepted alignment ID when the source originated in IOS space;
- dentist review state.

Real IOS/prosthetic sources (`registered_ios`, `prosthetic_scan`, `prosthetic_design`) require provenance. IOS-space sources must identify source documents covered by the current accepted IOS→CBCT alignment and use the matching source digest. DICOM-patient prosthetic artifacts must state the same source Frame of Reference UID as the stored target. A `dentist_defined` target is permitted only as explicit user-entered planning information; it is never inferred from teeth, anatomy, an IOS mesh, or an implant candidate.

Creation of a prosthetic target requires an accepted patient alignment so Dentora has one authoritative patient frame. A target is `pending_review` until a dentist explicitly accepts or rejects it. A stale target tied to an older/non-current alignment is not silently reused.

If prosthetic information is absent, `ProstheticPlanning.status` is `unavailable`, with no target object and no fabricated position or axis. Manual implant drafting may still be recorded, but prosthetic offset/axis measurements are explicitly `UNAVAILABLE`, and final plan acceptance plus deterministic prosthetic-guided proposal generation require an accepted prosthetic target.

## Deterministic engine

The backend engine uses NumPy, SciPy and trimesh for CPU-only physical geometry. It supports:

- parametric implant cylinder geometry from explicit catalog dimensions;
- prosthetic-guided candidate construction: platform exactly at the accepted target platform, axis exactly the accepted target axis, and candidate center derived deterministically from implant length;
- prosthetic platform-offset and directed-axis-angle measurements;
- finite-segment nerve-centerline distance, reported as implant-surface to nerve-centerline distance and **never** as canal-wall clearance;
- deterministic candidate ranking only from an explicit `PlanningPolicy` supplied by the caller.

No clinical thresholds or hidden margins are embedded in the engine. A geometric intersection can be reported as an intersection; it is not converted into a clinical `safe`/`unsafe` verdict. Deterministic proposals have status `PROPOSED`/`proposed` and never bypass dentist review.

## Missing data and bone-volume boundary

Missing clinical geometry is a first-class outcome. Quantitative checks return `UNAVAILABLE` with no fabricated numeric value. In particular, the current persisted DentalSegmentator/registration contract does not expose a provenance-preserving segmented bone volume. The default runtime therefore leaves bone envelope, height/axis span, width, contained-fraction and contained-volume checks unavailable rather than reconstructing bone from a point cloud, convex hull, CBCT intensity threshold or uncalibrated HU value.

The same rule applies to nerve data: without an accepted real `dicom_patient/mm` CBCT model-inference nerve pathway, the nerve measurement is unavailable. No synthetic pathway or legacy proximity band is substituted. Nerve centerline distance is not canal-wall clearance because the detected centerline does not contain a validated canal-wall surface/radius.

No CBCT HU/bone-quality classification is emitted by Implant Planning.

## Catalog and assets

An `ImplantCatalogEntry` carries explicit diameter/length dimensions plus dimension provenance and is represented geometrically by a parametric cylinder. Manufacturer-specific CAD/mesh assets are not required for planning and are not accepted as verified product geometry unless their license and provenance are independently established. The deterministic engine does not ship or load research-only/non-commercial implant-placement model weights.

## Plans, revisions and review

`DentalImplantPlan` owns plan identity and review state. `DentalImplantPlanRevision` is an immutable snapshot containing the candidate, assessment, planning case and optional explicit ranking policy. Any dentist edit creates a new revision, resets the plan to `draft`, and clears the prior review decision.

Statuses are:

- `draft` — dentist-authored or edited plan awaiting review;
- `proposed` — deterministic prosthetic-guided enumerated/ranked candidate awaiting review;
- `accepted` — explicitly accepted by a dentist, only with an available accepted prosthetic target;
- `rejected` — explicitly rejected by a dentist.

There is no automatic `safe`, `approved`, `final`, clinical-validity, bone-quality, or surgical-readiness state.

## ThreeUI

ThreeUI consumes the server-owned plan contract through the existing patient-space overlay path. It draws the parametric implant body and axis at the persisted center/axis in millimetres, renders the explicit prosthetic target marker/axis when available, shows measured facts and `UNAVAILABLE` checks, and exposes explicit edit/review actions. Rejected plans are not registered as active overlays.

The implant/prosthetic display is presentation-only. Rendering transforms never alter or replace stored patient coordinates. The rendered cylinder is a parametric representation of stored dimensions, not a manufacturer CAD asset.

## Validation boundary

Engineering validation covers analytic geometry fixtures, coordinate invariance, nerve-distance semantics, tangent/collision cases, deterministic reproducibility/ranking, prosthetic provenance and frame matching, missing-prosthetic and missing-bone fail-closed behavior, immutable revisions, dentist review, frontend patient-space projection, migrations, backend/frontend tests, typecheck, lint, E2E and Full CI.

This does not establish implant-planning clinical accuracy, prosthetic-fit validity, regulatory clearance, surgical suitability, or validated clinical safety thresholds.
