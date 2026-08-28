# Patient Presentation Mode — technical overview

`patient_presentation_mode` is a clinician-controlled, read-only projection built from the latest accepted AI Case Summary and the current authoritative Case Intelligence sources.

Flow: latest `AICaseSummary` → verify dentist acceptance/review provenance → re-read current Case Intelligence sources → compare source digest → project evidence-linked claims and data gaps → return ephemeral patient presentation.

The module fails closed when the latest summary is not accepted, review provenance is missing, case provenance is missing, the accepted summary is stale relative to the current case, or a claim has no evidence references.

The service does not materialize a new CaseSnapshot and does not write to patient, clinical, treatment, Dental3D, AI summary, or other canonical records.
