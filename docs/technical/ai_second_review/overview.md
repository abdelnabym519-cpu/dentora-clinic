# AI Second Review — Technical Overview

## Purpose

AI Second Review verifies the evidence/provenance coherence of the current Case Intelligence → Risk Engine → dentist-accepted AI Treatment Planning → Treatment Simulation chain, then asks the existing LLM provider for a constrained advisory discrepancy review.

## Fail-closed chain validation

Before an LLM call, the service requires exact agreement for CaseSnapshot source/version/contract, Risk Engine/policy/input/result digests, planning identity/version/output/reviewer provenance, Treatment Simulation contract/engine, and the simulation's planning linkage. It then recomputes the Treatment Simulation input digest, deterministically rebuilds the scene, and requires exact input-digest, scene, and output-digest equality.

Any stale or inconsistent link returns a conflict and no second-review artifact is generated.

## Privacy boundary

The LLM receives a structured projection only. Patient identifiers and raw clinical note/free-text fields are removed by the existing planning privacy path and redactor. Patient-space frame UIDs are stripped for Second Review; patient-space geometry validity is checked locally instead. Planning text is already generated from the redacted structured planning input. The simulation projection contains only its structured safety/checkpoint/risk-map representation, never mutated geometry.

## Structured output

The provider must return JSON with `findings` and `data_gaps`. Every finding is checked against allowlists for evidence IDs, deterministic risk-factor IDs, planning option/step refs, and simulation checkpoint refs. All unavailable/stale CaseSnapshot sections must be reproduced exactly as data gaps. Unknown references or omitted/invented gaps fail generation.

## Dentist control

New reviews start at `pending_review` with `clinical_output=false`. Only a dentist can mark the advisory artifact reviewed. This acknowledgement sets `clinical_output=true` for the review artifact only; `approves_treatment=false` and `mutates_canonical_records=false` remain invariant.
