# ADR 0026 — ThreeUI uses native DICOM patient space

- Status: accepted
- Date: 2026-08-25

## Decision

ThreeUI is presentation/infrastructure only. Its root represents the selected
DICOM Patient coordinate system in millimetres and always keeps identity
position, rotation and scale. Camera fitting may target a patient-space bounds
centre, but clinical objects are never centred, normalized or rescaled.

The browser may render an IOS mesh only when the latest persisted alignment is
dentist-accepted, its source document matches alignment provenance, its source
unit is millimetres, and its target Frame of Reference UID matches the selected
CBCT series. The server-issued SE(3) matrix is used verbatim; the browser never
calculates registration. Native CBCT anatomy and AI overlays require an explicit
`dicom_patient`/`mm` reference space, the same frame UID and provenance.

TresJS drives a Three.js WebGL2 renderer in on-demand mode. `three-mesh-bvh`
accelerates picking. Cornerstone3D owns DICOM decode, volume and MPR viewports;
views exchange only frame-qualified DICOM patient points. WebGPU is optional
future presentation infrastructure and is not the production baseline.

## Safety consequences

- Missing or mismatched registration fails closed; no overlay is guessed.
- Synthetic anatomy is never a clinical fallback.
- Measurements are created only from explicit user-picked patient points and
  remain millimetres in the selected patient frame.
- Rejected AI overlays are not registered; pending overlays remain visibly
  pending dentist review with provenance.
- All GPU, BVH, Cornerstone volume, tool-group and DICOM-file resources are
  disposed when their owning component is replaced or unmounted.

## Dependencies and licenses

- Three.js, TresJS core/Nuxt, Cornerstone3D core/tools/DICOM loader and
  `three-mesh-bvh` are MIT licensed.
- No 3D Slicer runtime, model weight, ML framework or new clinical algorithm is
  included by this decision.
