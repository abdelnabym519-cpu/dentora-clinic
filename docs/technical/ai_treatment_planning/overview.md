# AI Treatment Planning — technical overview

`ai_treatment_planning` consumes the current `CaseSnapshot` plus a deterministic Risk Engine evaluation of that exact snapshot. It does not mutate canonical treatment data.

Flow: current `CaseSnapshot` → deterministic Risk Engine evaluation → deterministic privacy projection → core `Provider` → strict JSON → evidence/risk-factor/data-gap validation → append-only planning artifact → dentist review.

The provider input contains no clinic/patient/source-record UUIDs and excludes clinical free-text note/narrative fields. Evidence uses deterministic aliases (`E001`, ...); treatment options and individual steps may reference only aliases present in the input. Risk references may use only deterministic Risk Engine factor IDs. Missing and stale CaseSnapshot sections remain explicit data gaps.

The output is advisory decision support only. It cannot create, update, schedule, price, prescribe, or execute a canonical `treatment_plan`; accepting a generated artifact changes review state only. Treatment Simulation and predicted-outcome generation are explicitly outside this module.
