# Orthodontic Planning — Events

All payloads carry **ids and status only** (no clinical measurements).

| Event | When | Payload keys |
|---|---|---|
| `orthodontic_planning.proposal_created` | a plan passed the safety gate and persisted as `draft` | `proposal_id`, `assessment_id`, `patient_id`, `clinic_id`, `provider`, `status`, `stage_count` |
| `orthodontic_planning.proposal_reviewed` | clinician approves/rejects a draft | `proposal_id`, `patient_id`, `clinic_id`, `decision`, `reviewed_by`, `reviewed_at` |
| `orthodontic_planning.plan_refused` | provider output failed the deterministic gate — **nothing is persisted** | `clinic_id`, `patient_id`, `assessment_id`, `provider`, `provider_version`, `hard_violations` (codes) |

Subscribers: none today. The events exist so audit trails, the patient
timeline, or future supervision tooling can observe planning activity
without coupling to the module.
