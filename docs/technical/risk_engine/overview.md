# Risk Engine + 3D Risk Map

The Risk Engine is a deterministic, append-only advisory analysis over the current `CaseSnapshot`. It consumes only structured, versioned evidence from Case Intelligence and preserves explicit source availability. Missing or stale inputs are never converted into zero risk.

## Contracts and semantics

Each factor is one of `present`, `absent`, `not_available`, or `invalid_or_stale`. Display bands are evidence-state labels only: `evidence_present`, `evidence_absent`, `data_gap`, `invalid_source`. There is no aggregate clinical risk score, low/medium/high clinical band, diagnosis, HU threshold, bone-quality assumption, or hidden clinical threshold.

Current policy evaluates only exact structured observations such as smoking/anticoagulant/bruxism/adverse-anaesthesia booleans, explicit closed-periodontogram boolean observations, accepted nerve-pathway presence, accepted current implant-plan presence, and the existing explicit implant-solid/nerve-centerline intersection flag. Free-text notes, comments and narratives are not evaluated.

## Provenance and determinism

Every result records CaseSnapshot version/contract, source digest, deterministic input digest, deterministic result digest, engine version, policy version, generated timestamp and availability state. Factors resolve through deterministic evidence aliases to persisted source references. The result digest excludes timestamps/review state, so replaying identical input under identical engine/policy versions yields the same digest.

## Persistence and review

Results are append-only and versioned per patient. Generation never overwrites an earlier result. The only state transition is dentist review from `pending_review` to `accepted` or `rejected`; review is single-transition and tenant scoped. Acceptance records review provenance but the contract remains `is_clinical=false`, `requires_review=true`, because this policy has not been clinically validated as a diagnosis or autonomous treatment decision.

## 3D Risk Map

The Risk Map reuses Dental3D `ClinicalScene`, `aiOverlayRegistry`, ThreeUI/TresJS/Three.js and the existing DICOM-patient/mm frame. It is `unavailable` unless the CaseSnapshot proves an accepted patient-specific alignment and validated anatomy. Only accepted patient-space nerve pathways and accepted implant-plan geometry can become regions. Frame mismatch, invalid geometry, rejected results or missing evidence fail closed. Synthetic/fallback clinical geometry is explicitly forbidden.

Risk regions carry factor IDs, evidence aliases, result provenance and evidence-state display bands. Their color/display is advisory visualization only and must not be interpreted as a diagnosis.

## Open-source dependencies

No new library, AI/ML model, model weights, Docker bundle or research-only artifact is added. The stage reuses the repository's already-governed Three.js/TresJS/three-mesh-bvh stack and existing Python infrastructure.

## Validation boundary

Required validation includes deterministic replay, source-change digest behavior, missing/stale propagation, patient-space preservation, fail-closed Risk Map behavior, no synthetic geometry, append-only persistence, dentist review, RBAC/tenant isolation, migrations, frontend rendering/gating and the full CI suite.
