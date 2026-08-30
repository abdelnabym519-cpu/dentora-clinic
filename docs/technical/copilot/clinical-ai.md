---
module: copilot
last_verified_commit: arena
---

# Copilot — Patient-scoped clinical AI features (B–F)

Five real, LLM-backed clinical features run **per patient** on top of the
existing Copilot/agent/LLM infrastructure. They share the exact same provider
abstraction, tool registry, RBAC, tenant isolation, privacy redaction and audit
pipeline as the conversational Clinical Copilot (feature A). Nothing here is a
hardcoded template, a deterministic rule labelled "AI", or a production mock.

| Feature | Endpoint | Output model |
| --- | --- | --- |
| B. Case Summary | `POST /api/v1/copilot/clinical/case-summary` | `CaseSummary` |
| C. Clinical Report | `POST /api/v1/copilot/clinical/report` | `ClinicalReport` |
| D. Second Review | `POST /api/v1/copilot/clinical/second-review` | `SecondReview` |
| E. Treatment Suggestions | `POST /api/v1/copilot/clinical/treatment-suggestions` | `TreatmentPlanAI` |
| F. Case Intelligence | `POST /api/v1/copilot/clinical/case-intelligence` | `CaseIntelligence` |

All bodies are `{ "patient_id": "<uuid>" }` and return the standard
`ApiResponse` envelope whose `data` is the validated feature model.

## Architecture / request path

```
HTTP POST (patient_id)
  → router._clinical_feature        (auth dependency: current_user + RBAC copilot.chat)
  → clinical.build_clinical_context
       • per-request Agent + AgentSession
       • resolves patient via READ tools through the tool registry
         (registry enforces clinic scope + RBAC + guardrails; SAVEPOINT per call)
       • gathers minimum-necessary records: patient, appointments, odontogram,
         treatments/treatment-plans, clinical notes/diagnoses, budgets,
         invoices, payments, recalls, timeline
       • PII redaction: names/phones are tokenised (NAME_…, PHONE_…) before
         leaving the server; raw PHI never enters the prompt
  → render_context_for_prompt        (deterministic input prep)
  → clinical._complete_json
       • get_provider() → Provider.complete()  (REAL streaming LLM call)
       • accumulate SSE text deltas
       • _extract_json: strip code fences, brace-scan the first JSON object
       • Pydantic model_validate against the feature schema
       • server stamps generated_by="ai", model, provenance sources BEFORE
         validation (the model cannot spoof or omit provenance)
  → response (or safe failure)
```

Deterministic input preparation → **real LLM inference** → structured
validation → response. There is no fabricated fallback: if the LLM is
unreachable or returns content that fails schema validation, the endpoint
fails safe with an explicit error (see [Failure modes](#failure-modes)).

## Permissions & tenant isolation

- Requires the authenticated user and the `copilot.chat` permission (same
  permission gate as the conversational copilot).
- The patient is **not** read directly by the service. Every record is fetched
  through the agent tool registry, which scopes every query to the caller's
  clinic and checks tool-level RBAC. A patient in another clinic, or a patient
  the caller cannot access, is not found → `404 PATIENT_NOT_FOUND`.
- Tested matrix: User A → Patient A **allowed**; User A → Patient B (other
  clinic) **404**; unauthenticated **401**; role without `copilot.chat`
  **403**.

## Privacy / minimum-necessary

- Only the READ tools needed for clinical context are invoked; no write/mutation
  tool is ever called by these features.
- Context is redacted through the shared `Redactor` before being sent to the
  model: patient names and phone numbers become opaque tokens and are
  rehydrated only inside the service boundary. Verified that raw names/phones
  never appear in the outgoing provider text.
- Feature **E (treatment suggestions)** only *suggests*. The AI never creates
  or executes a treatment plan; the treating clinician decides and acts through
  the normal deterministic treatment-plan workflow.

## Output contracts

Every result embeds the `ClinicalAIBase` envelope:

```
generated_by: "ai"          # server-stamped, constant
model: <provider model id>  # server-stamped
disclaimer: AI_DISCLAIMER   # fixed, non-authoritative wording
insufficient_information: bool
sources: [tool names that produced the context]   # server-merged provenance
```

Feature-specific fields (all validated by Pydantic):

- **CaseSummary** — `summary`, `current_condition[]`, `key_findings[]`,
  `active_treatments[]`, `important_history[]`, `outstanding_items[]`,
  `missing_information[]`, `uncertainty[]`.
- **ClinicalReport** — `title`, `overview`, `sections[]{heading, body,
  findings[]}`, `conclusions[]`, `recommendations[]`, `missing_information[]`,
  `uncertainty[]`.
- **SecondReview** — `overall_impression`, `key_findings[]`,
  `possible_concerns[]`, `inconsistencies[]`, `missing_information[]`,
  `questions_to_consider[]`, `confidence` (`low|medium|high`),
  `confidence_rationale`. Confidence is **capped** on sparse data: when the
  record set is too thin to justify it, a model-claimed `high` is downgraded.
- **TreatmentPlanAI** — `options[]{title, rationale, priority, estimated_steps[],
  depends_on_missing_info[], considerations[]}`, `suggested_order[]`,
  `missing_information[]`, `uncertainty[]`. Suggestions only; nothing executed.
- **CaseIntelligence** — hybrid: `signals[]` are **deterministic, server-computed
  rule outputs** (`kind`, `severity`, `message`, `source`) and are never
  authored or labelled by the model; `insights[]`, `risk_attention_points[]`,
  `missing_follow_up[]`, `missing_information[]`, `uncertainty[]` are the
  **LLM-based** portion. The two are kept in separate fields so deterministic
  signals are never misrepresented as AI.

## AI safety

- Fixed disclaimer on every result; output is explicitly "AI-assisted", never
  medical authority.
- The model is instructed to ground every statement in the supplied context, to
  invent no facts/diagnoses/records/tests, and to set
  `insufficient_information` / populate `missing_information` when records are
  inadequate.
- Provenance (`sources`) and `model` are attached by the server, not the model.
- AI never auto-executes irreversible actions (no treatment creation, no
  bookings, no writes).
- Deterministic clinical safety rules remain authoritative; the LLM cannot
  override them.

## Failure modes

Failing safe means **never** showing fabricated text. The router maps:

| Condition | HTTP | Error code (header `X-AI-Error-Code`) |
| --- | --- | --- |
| Patient not found / not in caller's clinic | 404 | `PATIENT_NOT_FOUND` |
| LLM provider raised / unreachable | 503 | `AI_UNAVAILABLE` |
| LLM returned non-JSON or schema-invalid content | 503 | `AI_INVALID_OUTPUT` |

The global HTTP exception handler renders the message; the machine-readable code
is also sent in the `X-AI-Error-Code` response header. On any AI failure the
frontend shows an explicit "AI unavailable / invalid response" state and never
renders partial or fake content.

## Configuration

Uses the existing provider factory and settings — no per-feature provider and no
committed secrets:

- `OPENAI_API_KEY` (or the configured AI gateway credentials) via environment.
- Model id comes from existing LLM settings; the resolved model is echoed in
  `model`.

> **Live inference status:** the implementation is complete and the real wire
> path is exercised in tests, but live external inference in this environment is
> **BLOCKED** — no `OPENAI_API_KEY` / outbound egress is available. Status:
> **IMPLEMENTED — LIVE INFERENCE BLOCKED**. Supplying credentials enables it with
> no code change.

## Testing

`backend/tests/test_copilot_clinical_ai.py` (13 tests):

- Parametrised happy path for all five features: `generated_by == "ai"`,
  `model` set, disclaimer present, `sources` include the patient read tool,
  provider invoked exactly once, JSON schema present in the system prompt.
- Deterministic-vs-AI separation (feature F signals are server-computed).
- PII redaction verified before the provider is called.
- Invalid (non-JSON) model output → safe `AI_INVALID_OUTPUT` (asserts header +
  message), no fabricated content.
- Provider exception → `AI_UNAVAILABLE`.
- Sparse-data high-confidence downgrade.
- Unauthenticated → 401; role without permission → 403; cross-tenant patient →
  404 `PATIENT_NOT_FOUND`.
- `test_openai_provider_wire_path_parses_structured_json`: drives the **real**
  `OpenAIProvider.complete()` SSE streaming decode via `httpx.MockTransport`
  injected into `openai.AsyncOpenAI` (no network), then `_extract_json` +
  `CaseSummary` validation + usage tokens — proving the production wire/parse
  path without mocking the code under test.

The provider is injected via monkeypatch in service-level tests; it is never
wired as a production fallback.

## Frontend

- Page: `frontend/module_layers/copilot/frontend/pages/copilot/clinical.vue`,
  linked from the Copilot page.
- Composable: `composables/useClinicalAI.ts` — per-feature
  `idle | loading | success | error` state; rejects any payload whose
  `generated_by !== "ai"` so a non-AI response can never render as a result.
- Handles idle, loading (skeleton, no fake content), success, AI-unavailable /
  invalid (error alert with retry), permission-denied (route guard 403), and
  `insufficient_information` (explicit notice).
- i18n keys under `copilot.clinical.*` in en/es/fr/pt/ar.

## See also

- [Copilot agentic architecture](./copilot-agentic-architecture.md)
- [Copilot overview](./overview.md)
- Module notes: `backend/app/modules/copilot/CLAUDE.md`
