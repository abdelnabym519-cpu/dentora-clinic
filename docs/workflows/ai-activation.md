# AI Activation — Local Operations & Verification Guide

This document describes the AI/clinical-intelligence capabilities that ship
**activated**, how to configure the local LLM provider, how to run the Voice
STT dependency, and how to verify everything locally. It records only what is
implemented in the repository today.

## Activated modules (auto-installed)

The following official modules are part of the default install
(`manifest.auto_install = true`). A fresh environment gets them automatically
during the boot reconcile; existing environments promote them through the
normal module-install flow (Settings → Modules, the platform API, or the CLI —
see below). **Installing a module is not the same as exposing it**: each one
ships its own Nuxt layer, registered into `frontend/modules.json`, and renders
inside the patient Summary workflow.

| Module | Nature | UI surface | Notes |
|---|---|---|---|
| `copilot` | Real LLM (agentic) | Sidebar **Copilot** + overlay drawer + `/copilot` + settings | Provider required for chat; confirmations/nudges/digest work without |
| `voice` | Deterministic intent (no LLM) | Microphone overlay (permission `voice.use`) | Needs the local STT runtime (below) |
| `dental_3d` | Deterministic + external ML services | Patient Summary cards: 3D viewer, implant planning, risk map | Nerve/registration need operator-run model services |
| `case_intelligence` | Deterministic evidence aggregation | Patient Summary: Case Intelligence card | No AI reasoning by design (ADR 0027) |
| `risk_engine` | Deterministic CDS | Risk Engine card (ships in the `dental_3d` layer) | Rules, not ML — never labeled diagnosis |
| `ai_case_summary` | Real LLM, evidence-traceable | Patient Summary: AI Case Summary card | Claims + data gaps + mandatory dentist review |
| `ai_treatment_planning` | Real LLM, evidence-traceable | Patient Summary: AI Treatment Planning card | Advisory options; dentist accept/reject required |
| `treatment_simulation` | Deterministic | Patient Summary: Treatment Simulation card | Requires a dentist-ACCEPTED plan option |
| `ai_second_review` | Real LLM | Patient Summary: AI Second Review card | Requires a simulation; approves nothing |
| `ai_clinical_report` | Real LLM (pipeline compilation) | Patient Summary: AI Clinical Report card | Readiness gates + explicit limitations |
| `clinical_copilot` | Real LLM behind readiness gates | Patient Summary: Clinical Copilot card | Dentist-only by safety design (`dentist_control_required`) |

## Synthetic AI demo dataset (one command)

`python scripts/seed_demo.py` now also seeds five clearly-marked **synthetic**
demo patients with structured clinical evidence (module-gated, idempotent, and
refusing to run with `ENVIRONMENT=production`):

| Patient | Archetype | Evidence highlights |
|---|---|---|
| Nora Farouk (SYNTHETIC) | clean baseline | healthy dentition, healthy closed periodontogram |
| Omar Sami (SYNTHETIC) | restorative | caries + fillings/planned composites |
| Layla Adel (SYNTHETIC) | periodontal risk | smoker + closed perio with BOP/plaque/suppuration |
| Sam Youssef (SYNTHETIC) | implant planning | missing teeth + synthetic scan geometry |
| **Amina Hassan (SYNTHETIC)** | **Complete AI Demo Case** | anticoagulants, anesthesia reaction, bruxism, smoking, allergy, medications, hypertension, caries, failing restoration, generalized periodontitis (closed perio), synthetic scan |

The complete case exercises the chain **Case Intelligence → Risk Engine
(7/10 observed-fact factors genuinely present) → AI Treatment Planning →
dentist acceptance → Treatment Simulation → AI Second Review → AI Clinical
Report → Clinical Copilot**. All data is fictional; every row is marked
synthetic. The seeder also pins the demo clinic's Copilot engine to the local
provider: **Ollama / `qwen3:8b`** (per-clinic `copilot_settings` — change in
Settings → Copilot if desired).

Fresh environment:

```bash
docker compose up -d          # backend boots, modules auto-install
docker compose exec backend python scripts/seed_demo.py
```

Existing environment (modules not yet installed): run the install commands
above first, then the seed.

**Reconciling behavior (existing demo databases).** The seeder no longer
stops at "clinic exists": when the demo clinic is already present it
preserves every existing clinic/user/patient untouched and reconciles only
the synthetic AI demo cases — missing patients are created, existing ones
are left as-is, and repeated runs are no-ops. A database seeded before this
dataset existed is therefore brought to the full demo state by the same one
command, with no destructive reset.

Local stack ports (docker-compose.yml): frontend `3100`, backend `8100`,
database host port `55434`; host Ollama is reached by the backend at
`host.docker.internal:11434`.

## Activating on an existing environment

Fresh databases install the modules above automatically. A database created
*before* activation now catches up on its own: at boot
`ModuleService.reconcile_with_db()` sees an `uninstalled` row whose manifest
declares `auto_install: true`, schedules it (`to_install`), and the pending
processor runs the normal migrate → seed → lifecycle → finalize pipeline in
dependency order, after which the layer sync rewrites
`frontend/modules.json`. So activation on an existing environment is:

```bash
docker compose restart backend            # reconcile promotes + installs + syncs
docker compose logs --since 3m backend | grep "scheduled for install"
python -m app.cli modules doctor          # no orphans, no missing layer dirs
```

One exception, by design: a module an administrator **uninstalled on purpose**
is never resurrected — the operation log outranks the manifest default. To
re-activate such a module (or to install one whose manifest is still
`auto_install: false`), use the official tooling:

```bash
python -m app.cli modules install clinical_copilot
python -m app.cli modules sync-frontend   # regenerate frontend/modules.json
```

(or install them one by one from **Settings → Modules** in the admin UI).
`modules.json` lists the Nuxt layers to compile; the backend writes it on
install and on every non-production boot, the CLI can rewrite it at any time,
and production images generate it from the layers baked into the image.

## Local LLM provider (Copilot + clinical AI generation)

Defaults (`backend/app/config.py`): provider `openai`, Ollama base URL
`http://host.docker.internal:11434/v1/`, Ollama chat model `qwen3:8b`.

Local Ollama setup (no cloud dependency):

```bash
ollama pull qwen3:8b
# then in the app: Settings → Copilot → provider = ollama
# (per-clinic override stored by PATCH /api/v1/copilot/settings)
```

Cloudflare Workers AI is also supported (`CLOUDFLARE_ACCOUNT_ID` +
`CLOUDFLARE_API_TOKEN`). When no provider is reachable, generation endpoints
return an explicit `503 …_provider_unavailable` (or the copilot chat stream
emits an `error` SSE frame) — the UI shows the actionable state and never a
fabricated result.

Two knobs control which provider is used where:

* **Copilot chat** — per-clinic selection via Settings → Copilot
  (`PATCH /api/v1/copilot/settings`; the demo seed pins it to
  `ollama`/`qwen3:8b`).
* **Clinical-AI generation** (case summary, case intelligence, treatment
  planning, second review, clinical report, clinical copilot) — the
  deployment-level default `COPILOT_PROVIDER_DEFAULT` (see
  `backend/app/config.py`).

  Leave it **empty** (the shipped default) and `ENVIRONMENT` decides:
  `production` resolves `cloudflare`, every other environment resolves
  `ollama`, so a local stack runs fully offline against the models already
  pulled on the host. Set it explicitly to pin `openai`, `ollama` or
  `cloudflare`. A clinic's own `copilot_settings` row still wins — and
  because those rows are lazy-created once and never re-derived, a row
  written under an older default keeps it until you change it in
  Settings → Copilot.

  It previously defaulted to `openai` with an empty `OPENAI_API_KEY`, so a
  fresh local install sent every AI request to OpenAI with no credential and
  the UI could only report a bare "Connection error".

Reaching a host-local Ollama from the backend container needs all of:

| Requirement | Check |
| --- | --- |
| Ollama running | `curl http://localhost:11434/api/tags` |
| Listening beyond loopback | run it with `OLLAMA_HOST=0.0.0.0` (the default binds `127.0.0.1`, which a container cannot reach) |
| `host.docker.internal` resolves in the container | `docker-compose.yml` declares `extra_hosts: ["host.docker.internal:host-gateway"]` — required on Docker Engine, automatic only on Docker Desktop |
| Model pulled | `ollama pull qwen3:8b` (Ollama answers 404 for a model it does not have) |

Transport failures are translated into the neutral error hierarchy
(`LLMUnavailableError`, an `LLMConfigError`) carrying which host was tried
and which of the four checks above to look at, so the endpoints answer
`503 …_provider_unavailable` with that text instead of a `500` the UI can
only render as "Connection error". Vendor credential rejections
(`AuthenticationError`) keep their type — a wrong key is a different state
from an unreachable provider.

## Voice STT runtime

Voice intent recognition is deterministic (regex + fuzzy matching over
transcripts — no LLM). Speech-to-text is an **operator-run local
faster-whisper** runtime: the browser sends microphone audio only to that
loopback service, never to the Dentora backend. When the runtime is not
running, the mic overlay shows `Local voice runtime unavailable` instead of
failing silently.

## Which capabilities are NOT implemented

* ML tooth segmentation (current segmentation is deterministic arch
  partitioning behind the provider port)
* nerve/mandibular-canal inference **inside** the app (requires the optional
  operator-managed inference service; without it the API returns an explicit
  unavailable/`missing_model` state — see `docker-compose.nerve-ai.yml`)
* pathology detection ML, digital-twin AI, embeddings/RAG/pgvector retrieval
* the cancelled Dental Radiograph Intelligence phase (intentionally absent)

## Local verification recipe

```bash
# provider first: resolves config, DNS, TCP, model availability, and with
# --probe runs one real completion through the production provider object.
# Exit status 0 = usable; the failure lines name the exact thing to fix.
docker compose exec backend python -m scripts.diagnose_ai_provider --probe --db

# backend: boot, then
curl -s localhost:8100/api/v1/modules/-/active -H "Authorization: Bearer $TOKEN"
# → all modules above listed as active

# deterministic engines (no provider needed)
curl -X POST localhost:8100/api/v1/risk_engine/patients/$PID -H "Authorization: Bearer $TOKEN" -d '{}'
curl -X POST localhost:8100/api/v1/dental_3d/patients/$PID/segmentation -H "Authorization: Bearer $TOKEN" -d '{}'

# provider-gated generation (needs the provider configured)
curl -X POST localhost:8100/api/v1/ai_case_summary/patients/$PID -H "Authorization: Bearer $TOKEN" -d '{}'

# frontend: layers must be present in frontend/modules.json before `nuxt build`
grep -c module_layers frontend/modules.json
# if an AI feature has no navigation entry, the artifact is stale — it is
# generated from *installed* modules, so regenerate and rebuild:
docker compose exec backend python -m app.cli modules sync-frontend
```
