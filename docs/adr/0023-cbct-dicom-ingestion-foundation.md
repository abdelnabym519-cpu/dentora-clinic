# 0023 — CBCT/DICOM ingestion through media and geometry-source ports

- **Status:** accepted
- **Date:** 2026-08-24
- **Deciders:** Mohamed Abdelnaby (maintainer), Dentora core team
- **Tags:** dental-3d, cbct, dicom, media, clean-architecture, security

## Context

Dental 3D already assembles a patient scene through the framework-free
`DentalGeometrySource` port (ADR 0020), stores real scan bytes exclusively in
the media module, and preserves a synthetic geometry fallback. Phase 5.1 needs
CBCT/DICOM data ingestion and normalized data availability, but explicitly not
pixel rendering, diagnosis, patient-specific nerve alignment, clinical
detection, implant planning or surgical planning.

DICOM parsing is a specialized external capability. Reimplementing the file
format would be unsafe; allowing its library into domain/application code would
violate ADR 0019. A second CBCT table or filesystem would duplicate media's
clinic/patient ownership, archival and authorized-download rules.

## Decision

1. `cbct.py` defines framework-independent contracts and the
   `DicomIngestionPort`; `cbct_service.py` is a port-only application use case.
   DICOM vendors, pydicom, FastAPI, SQLAlchemy and storage are absent from both.
2. `PydicomMediaCbctAdapter` is infrastructure. It accepts DICOM Part 10 CT
   instances (`.dcm`/`.dicom`, `application/dicom` or browser octet-stream),
   reads a strict header allowlist with `stop_before_pixels=True`, validates
   required UIDs and geometry metadata, and never decodes Pixel Data.
3. Raw instances are ordinary media `Document` rows with canonical MIME
   `application/dicom`. Normalized metadata is stored under the existing
   `documents.extra_data.dental_3d_cbct` extensibility field. No identifying
   tags are copied into normalized responses. Media remains the only byte
   owner and download authorization boundary.
4. `CbctDicomGeometrySource` implements the existing
   `DentalGeometrySource` port. It discovers active clinic+patient-scoped media
   documents, groups them into non-diagnostic series availability descriptors,
   and ignores archived/malformed metadata. The scene's render generator stays
   synthetic/intraoral because availability is not renderable geometry.
5. The minimal presentation surface is one `dental_3d.write` endpoint for a
   DICOM instance; scene reads expose `cbct_series`. There is no Phase 5.1 UI,
   no migration and no new permission.
6. pydicom is constrained to `>=3.0.2,<4.0`. Version 3.0.2 is the security
   release that fixes CVE-2026-32711. Phase 5.1 does not process DICOMDIR, but
   it rejects DICOMDIR explicitly and retains the patched floor.

## Consequences

### Good

- Clean Architecture dependency direction remains inward and the parser is
  replaceable without changing application contracts.
- Existing media clinic isolation, storage paths, archival, events and RBAC
  are reused; no parallel persistence lifecycle exists.
- Synthetic and intraoral sources keep their behavior and ordering.
- Normalized output describes data availability only and carries a fixed
  `non_diagnostic=true` safety marker.

### Bad / accepted trade-offs

- Phase 5.1 accepts Part 10 CT instances only. Raw datasets without a DICM
  preamble and non-CT modalities require a later explicit decision.
- Upload is one instance per request; archive/batch packaging and resumable
  series upload are deferred.
- Discovery is bounded to 2,048 active instances and 32 series per patient;
  descriptors set `catalog_truncated=true` when either bound is reached;
  pagination/selection is deferred.
- No pixel decoding means the foundation does not prove pixel-data integrity
  or offer volumetric rendering.

## Alternatives considered

- **A new `dental_cbct_series` table and storage tree** — rejected: duplicates
  media ownership and creates an unnecessary migration/uninstall problem.
- **A home-grown DICOM parser** — rejected: unnecessary security and
  compatibility risk for a mature standard.
- **Decode pixels or generate a surface mesh now** — rejected: expands into
  visualization/clinical processing beyond Phase 5.1.
- **Store or expose all DICOM tags** — rejected: copies identifying/vendor data
  beyond what normalized availability requires.

## How to verify the rule still holds

- `tests/modules/dental_3d/test_cbct_contracts.py` — inner contracts, literals,
  stable errors and port-only application dependency.
- `tests/modules/dental_3d/test_cbct_ingestion.py` — Part 10/CT validation and
  existing-media persistence without normalized identity fields.
- `tests/modules/dental_3d/test_cbct_api.py` — API RBAC, clinic isolation,
  series composition, media downloads and archival behavior.
- `rg "fastapi|sqlalchemy|pydicom|app.modules.media" backend/app/modules/dental_3d/cbct.py backend/app/modules/dental_3d/cbct_service.py`
  must be empty.

## References

- `docs/adr/0019-clean-architecture-standard.md`
- `docs/adr/0020-real-mesh-ingestion.md`
- `backend/app/modules/media/models.py`
- [pydicom 3.0.2 release](https://github.com/pydicom/pydicom/releases/tag/v3.0.2)
- [pydicom license](https://github.com/pydicom/pydicom/blob/main/LICENSE)
- [CVE-2026-32711 advisory](https://github.com/pydicom/pydicom/security/advisories/GHSA-v856-2rf8-9f28)
