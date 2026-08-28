# Case Intelligence — technical overview

`case_intelligence` materializes a deterministic, versioned evidence snapshot of the authoritative clinical state already owned by Dentora modules. It is informational infrastructure only: it does not diagnose, score risk, generate clinical narrative, recommend treatment, or mutate canonical clinical records.

## Contract

The server builds `CaseSnapshot` version `1.0` from authoritative sources. Every section carries an explicit availability state: `available`, `not_available`, or `invalid_or_stale`. Missing data remains missing; it is never converted into zero, normal, safe, negative, or inferred values.

The snapshot contains patient/case identity references, patient-space/reference-frame metadata when backed by an accepted patient-specific alignment, structured clinical sections, provenance/evidence references, a missing-data report, source versions/digests, a deterministic source digest, generation time, and an append-only snapshot version.

## Deterministic aggregation

`CaseAggregator` is pure. Source rows are normalized and ordered before aggregation, evidence references are sorted, and the source digest is calculated from canonical JSON. `generated_at` and the persistence version are not part of the source digest. Therefore identical authoritative input and contract versions map to the same digest.

`CaseIntelligenceService` reuses the existing latest snapshot when that digest has not changed. A changed authoritative source produces a new append-only version. Historical versions are returned exactly from Case Intelligence persistence.

## Source boundaries

The SQLAlchemy source provider reads patient core data, normalized medical context/history, odontogram and treatment history, the latest periodontogram state, patient timeline, media/imaging metadata, accepted/validated Dental3D evidence, native validated IOS/CBCT availability, accepted patient-specific alignment, accepted prosthetic targets, validated nerve evidence, and current immutable Implant Planning revisions where available.

Validated CBCT anatomy is fail-closed: anatomy is only `available` when an accepted alignment contains explicit anatomy model identity/version plus CBCT provenance. A reviewed segmentation record alone is not promoted to validated CBCT anatomy.

## Persistence and reproducibility

`case_intelligence_snapshots` is an append-only application model. Canonical source modules remain owners of their data. Case Intelligence has no update/delete API and never writes back to patient, odontogram, periodontogram, medical, media, anatomy, nerve, alignment, prosthetic, or Implant Planning records.

Concurrent materialization for the same patient is serialized by locking the patient identity row before version selection/insertion; no canonical field is changed by that lock.

## API

`GET /api/v1/case_intelligence/patients/{patient_id}` returns the current server-built snapshot, creating a new append-only version only when authoritative inputs changed. `?version=N` returns a historical persisted version. No endpoint accepts a client-supplied `CaseSnapshot` as canonical input.
