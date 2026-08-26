# Patient Presentation Mode

Patient Presentation Mode is a dentist-controlled chairside view of already reviewed clinical output. It is not a diagnosis engine, treatment planner, approval mechanism, or patient-record editor.

## Data flow

1. Resolve clinic-scoped access through the existing authentication context.
2. Require the `patient_presentation_mode.read` permission and the dentist role.
3. Read the latest AI Case Summary.
4. Require `accepted` review state plus reviewer and review timestamp provenance.
5. Read authoritative Case Intelligence source adapters without materializing a new snapshot.
6. Recompute the current source digest and compare it with the digest recorded on the accepted summary.
7. If the digest differs, return a fail-closed stale state (`409`).
8. Otherwise return the accepted claims verbatim with their evidence aliases and explicit data gaps.

## Persistence and storage

The module has no database model, migration, upload path, object-store write, or canonical-record mutation. The response is ephemeral. Existing Storage Integration remains the storage gate for the final SHA.

## Clinical safety

- No autonomous diagnosis or treatment decision.
- No new LLM invocation.
- No invented or rewritten clinical facts.
- No display of pending/rejected output.
- Evidence aliases remain attached to every claim.
- Missing/stale information stays explicit.
- Current-source mismatch prevents presentation.
- Dentist control is mandatory.

## Dependencies

Only `patients`, `case_intelligence`, and `ai_case_summary`. The module does not depend on Treatment Simulation, Clinical Copilot, AI Second Review, or AI Clinical Report.
