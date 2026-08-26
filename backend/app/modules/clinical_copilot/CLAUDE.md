# Clinical Copilot

## Purpose
Clinical Copilot is a dentist-controlled advisory surface over already materialized clinical intelligence artifacts.
It never diagnoses, selects treatment, approves a plan, or mutates canonical patient or clinical records.

## Inputs
- Case Intelligence snapshot and its evidence provenance.
- Risk Engine result bound to the same snapshot.
- Dentist-reviewed AI Treatment Planning artifact.
- Treatment Simulation bound to that reviewed plan.
- AI Second Review through an injected read-only port.

## Safety contract
Advice fails closed when any required stage is missing, unavailable, or provenance-stale.
Provider payloads contain structured redacted evidence only; direct identifiers and unrestricted note fields are removed.
Every generated claim must cite evidence IDs supplied by the evidence chain.
Tool calls from the LLM are rejected and no tool registry is exposed.
Dentist review remains mandatory and all output is explicitly advisory.

## HTTP API
`GET /api/v1/clinical-copilot/patients/{patient_id}/context` returns chain readiness and blockers.
`POST /api/v1/clinical-copilot/advise` generates evidence-cited advisory text only when the chain is ready.

## Permissions
`clinical_copilot.read` can inspect the evidence chain.
`clinical_copilot.use` is granted to dentists for advisory generation.

## Persistence
This module defines no tables and writes no upstream artifacts. It reads existing append-only artifacts only.
