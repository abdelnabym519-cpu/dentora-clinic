# Clinical Copilot

## Purpose
Clinical Copilot is a dentist-controlled advisory surface over already materialized clinical intelligence artifacts.
It never diagnoses, selects treatment, approves a plan, or mutates canonical patient or clinical records.

## Inputs
- Complete, current Case Intelligence snapshot and its evidence provenance.
- Current Risk Engine result bound to the same snapshot and available for use.
- Dentist-accepted AI Treatment Planning artifact with reviewer/timestamp provenance.
- Treatment Simulation bound to that accepted reviewed plan and current risk/case evidence.
- AI Second Review through an injected read-only port, with accepted-review provenance when available.

## Safety contract
Advice fails closed when any required stage is missing, unavailable, incomplete, unreviewed where review is required, or provenance-stale.
Provider payloads contain structured redacted evidence only. Direct identifiers, source-record identifiers, and unrestricted narrative/note fields are removed before the existing Dentora `Redactor` is applied.
Every generated claim must cite evidence IDs supplied by the evidence chain.
Tool calls from the LLM are rejected and no tool registry is exposed.
Advisory generation is dentist-only at both the router and service boundary.

## HTTP API
`GET /api/v1/clinical-copilot/patients/{patient_id}/context` returns chain readiness and blockers.
`POST /api/v1/clinical-copilot/advise` accepts only a finite `focus` intent and generates evidence-cited advisory text only when the chain is ready.

## Permissions
`clinical_copilot.read` can inspect the evidence chain.
`clinical_copilot.use` is granted to dentists for advisory generation.

## Provenance
Generated advice includes provider/model, input digest, output digest, generator identity, and the upstream stage status/provenance snapshot used for that output.

## Persistence
This module defines no tables and writes no upstream artifacts. It reads existing append-only artifacts only.
