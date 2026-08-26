# Changelog — Treatment Simulation

All notable changes to this module are documented here.

## [Unreleased]

- No unreleased changes.

## [1.0.0] - 2026-08-26

- Added deterministic Treatment Simulation over dentist-accepted AI Treatment Planning options.
- Added Dental Digital Twin scene contracts that preserve accepted DICOM patient-space coordinates and the deterministic Risk Map without synthetic or mutated geometry.
- Added fail-closed stale-evidence validation against Case Intelligence and Risk Engine provenance.
- Added append-only multi-tenant simulation persistence with deterministic input/output digests and accepted-plan review provenance.
- Added clinic-scoped create/latest/history APIs and module RBAC.
- Added explicit non-predictive safety invariants; no biological outcome forecasting, canonical treatment-plan writes, or AI Second Review.
