# Changelog

All notable changes to Clinical Copilot are documented here.

## [Unreleased]
- Added read-only evidence-chain assembly across Case Intelligence, Risk Engine, AI Treatment Planning and Treatment Simulation.
- Added fail-closed AI Second Review port so unavailable review context remains explicit.
- Added strict incomplete/stale/unavailable gates and accepted dentist-review provenance checks for reviewed upstream artifacts.
- Added structured PHI-minimized provider payloads using the existing Dentora Redactor, excluding direct and source-record identifiers plus unrestricted narrative fields.
- Added evidence-cited advisory output validation, output digest, upstream provenance snapshot and generator identity.
- Added dentist-only generation at router and service boundaries with no tools and no canonical clinical record mutations.

## [1.0.0] - 2026-08-26
- Initial Clinical Copilot advisory contract.
