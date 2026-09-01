# AI Clinical Report

`ai_clinical_report` produces a **draft, advisory-only** clinical report for a dentist from the reviewed Dentora clinical evidence chain. It is deliberately non-canonical: generation does not create or update patient, anatomy, diagnosis, treatment-plan, simulation, or review records.

## Inputs

The module reuses the guarded Clinical Copilot context and requires all five upstream stages to be ready:

1. Case Intelligence
2. Risk Engine
3. AI Treatment Planning with accepted dentist review
4. Treatment Simulation matching the accepted plan
5. AI Second Review matching the current simulation and accepted by a dentist

The AI Second Review record is accessed through a read-only adapter scoped by `clinic_id` and `patient_id`.

## Fail-closed behavior

If any stage is missing, unavailable, stale, mismatched, or not review-complete, readiness is false and generation returns the existing clinical-context-insufficient error. The module never regenerates or repairs upstream artifacts automatically.

## Privacy and provider boundary

Generation uses Dentora's existing vendor-neutral LLM provider through `ClinicalCopilotGuardedService`. Direct identifiers and unrestricted narrative are removed by the established structured redaction and opaque-ID boundary before cloud provider execution. This module adds no new free-text provider input.

## Evidence and provenance

Clinical Copilot validates every AI claim against allowed upstream evidence IDs. AI Clinical Report then organizes those already-validated claims deterministically into stage sections. A claim that cannot be mapped to upstream evidence causes report assembly to fail rather than being displayed.

Each report includes the provider and model, source advisory input/output digests, a report output digest, upstream stage provenance, generation timestamp, and generating user ID.

## Lifecycle

The v1 report status is always `draft`. `dentist_review_required` is always true. There is no approval endpoint, no persistence model, and no automatic mutation of canonical clinical records.
