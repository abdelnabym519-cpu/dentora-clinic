# Patient Presentation Mode

Patient Presentation Mode is a clinician-controlled, read-only projection of the latest AI Case Summary for chairside discussion with a patient.

## Safety contract

- Only a dentist with `patient_presentation_mode.read` may open the mode.
- The latest AI Case Summary must be accepted and have complete dentist-review provenance.
- Every displayed claim is copied from the accepted summary and keeps its evidence aliases; the mode does not create or rewrite clinical facts.
- Missing and stale source states remain explicit.
- Authoritative case sources are re-read before rendering. If their digest differs from the accepted summary, the presentation fails closed as stale.
- No canonical patient, anatomy, treatment, case-intelligence, or summary record is changed.
- The response is ephemeral and is not persisted by this module.

## API

`GET /api/v1/patient_presentation_mode/patients/{patient_id}`

Safe failures are explicit: missing source returns `404`; unaccepted, incomplete-provenance, or stale output returns `409`; non-dentist access returns `403`.
