# AI Case Summary

AI Case Summary converts the current Case Intelligence `CaseSnapshot` into a concise advisory set of evidence-linked observed facts and explicit data gaps.

The LLM never receives the raw snapshot. A privacy projection removes direct identifiers, source UUIDs, and clinical free-text fields before the existing Dentora redactor is applied. The model output is then schema-validated and rejected unless every claim references known evidence and every unavailable/stale section is preserved as a data gap.

Each persisted summary records its Unified Clinical Case (`CaseSnapshot`) version/source digest, provider/model, provider contract version, prompt version, input digest and output digest. New summaries are not clinical output until a dentist explicitly accepts them.
