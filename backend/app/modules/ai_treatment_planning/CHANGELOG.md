# Changelog — AI Treatment Planning

All notable changes to this module are documented here.

## [Unreleased]

- No unreleased changes.

## [1.0.0] - 2026-08-26

- Added redacted CaseSnapshot + deterministic Risk Engine planning input.
- Added strict structured option/step evidence validation and explicit data-gap propagation.
- Added append-only multi-tenant persistence with provider/model/input/output provenance.
- Added latest/history APIs and mandatory dentist review workflow.
- Added a hard no-automatic-execution boundary: accepted AI output never creates a canonical treatment plan.
