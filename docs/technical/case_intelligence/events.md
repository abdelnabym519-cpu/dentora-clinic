# Case Intelligence events

## `case_intelligence.snapshot.created`

Published after a new append-only Case Intelligence snapshot is committed. It is not published when the latest snapshot is reused for identical authoritative inputs.

Payload contains only audit/provenance identifiers and version metadata: `clinic_id`, `patient_id`, `snapshot_id`, `snapshot_version`, `contract_version`, and `source_digest`. Clinical snapshot contents are not copied into the event payload.

Case Intelligence does not subscribe to clinical events in this stage; aggregation is explicit and read-time. It also does not write a patient-timeline event because the timeline is itself an aggregation input and doing so would create artificial version churn.
