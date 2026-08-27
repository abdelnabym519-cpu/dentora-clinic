# AI Case Summary — technical overview

`ai_case_summary` depends only on `case_intelligence`. The `CaseSnapshot` is the Unified Clinical Case source of truth for this stage.

Flow: current `CaseSnapshot` → deterministic privacy projection → core `Provider` → strict JSON → evidence/gap validation → summary persistence → dentist review.

The provider input contains no clinic/patient/source-record UUIDs and excludes free-text note/narrative fields. Evidence uses local aliases (`E001`, ...). Claims must reference aliases present in the input. A missing or stale CaseSnapshot section cannot be promoted to an observed clinical fact.

Persistence stores only the AI output and provenance/review metadata. It has no write path to patient, anatomy, Dental3D, Implant Planning, treatment or other canonical data. No Three/Tres/renderer types exist in the module.
