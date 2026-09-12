# Dentora — AI Frontend Runtime Provisioning Repair

**Branch:** `arena/01a091f7-dentora-clinic` · **Base:** `f1c79ca` (`main`, untouched)
**Commits for this mission:** `92edfef` (provisioning fix), `dd73f5b` (test + catalog follow-through), plus this document
**Scope:** the 9 approved AI Activation modules only. The cancelled Dental Radiograph Intelligence 7-feature phase was not touched, revived, or referenced.

---

## 1. ROOT CAUSE

On this branch — which descends from `main` — the nine AI modules are **backend-only**: their manifests declared no `frontend.layer_path`, so `backend/app/core/plugins/frontend_layers.collect_layers()` never emitted an entry for them, so the backend-written `frontend/modules.json` never listed them, so `frontend/nuxt.config.ts`'s `extends: moduleLayers` never included them, and the canonical implementations of `useCaseIntelligence.ts`, `useAICaseSummary.ts`, `useAITreatmentPlanning.ts`, `useAISecondReview.ts`, `useAIClinicalReport.ts`, `useClinicalCopilot.ts`, `useTreatmentSimulation.ts`, their seven `<Module>Card.vue` surfaces, their `slots.client.ts` registrations and `frontend/app/utils/aiErrors.ts` (`aiActionableError`) existed on **exactly one unmerged ref in the repository: PR #65 `feat/ai-activation` @ `72216a1a330f69ed21bea3b3babc9d607f4cf08b`**. This is your case **A + E + H** at once: missing canonical source, an incomplete/stale generated `modules.json`, and a layer list produced by a different code state. Nothing was ever renamed or moved — `git grep` across every tracked file and `git log --all -S <symbol>` across every locally available ref return **zero** hits for all eight symbols, and the seven module directories had no `frontend/` folder at all.

Why the container showed the layer directories but not the files: `docker-compose.yml` bind-mounts `./backend/app/modules` at `/module_layers:ro`, so `/module_layers/case_intelligence` exists as soon as the *module* exists, with or without a frontend layer inside it. `frontend/modules.json` is a **generated artifact** written by the backend into the host-mounted `./frontend` (`DENTORA_FRONTEND_ROOT=/host_frontend`, paths rendered with `DENTORA_MODULE_LAYERS_MOUNT=/module_layers`), and `resolve_layer_path()` only emits a layer whose directory actually exists — so the file listing those AI layer paths was written while a tree that *had* them was mounted, and it survived the switch back to a tree that does not. Nuxt then extended layer paths whose composables were absent, and its auto-import registry still carried entries for them: `[NUXT_B6005] Could not resolve /module_layers/<module>/frontend/composables/use<Module>.ts`. Same story for `/app/app/utils/aiErrors.ts`.

The correct fix was therefore **not** to write replacement composables (that would have created a second, divergent implementation of an existing AI module) but to restore the canonical ones and make the provisioning chain declare them, then let the existing generator do its job.

**Provisioning chain, as it actually works in this repository:**

```
module manifest: frontend.layer_path="frontend", auto_install=True
  → ModuleService.reconcile()          state=installed at boot (only for NEW records)
  → PendingProcessor.run()             every boot, applies pending installs
  → processor._sync_frontend_layers()  skipped when ENVIRONMENT=production
  → frontend_layers.collect_layers()   requires the layer dir to exist on disk
  → frontend_layers.write_modules_json()  atomic write to frontend/modules.json
  → nuxt.config.ts loadModuleLayers()  extends: [<layer>, ...]
  → Nuxt scans each layer's composables/ components/ plugins/
  → plugins/slots.client.ts            registerSlot('patient.summary.cards', {permission})
  → patients/frontend/pages/patients/[id].vue:215  resolve('patient.summary.cards', {patient})
  → the card renders on the patient file, permission-gated
```

In production the same layers are baked into the image instead (`frontend/Dockerfile.prod:11` → `COPY backend/app/modules /module_layers`), which is why `_sync_frontend_layers()` short-circuits there. Both paths are satisfied by this fix: the files are in the tree, so dev bind-mounts resolve and prod `COPY` includes them.

---

## 2. EXACT FIX

51 files changed, +2126 / −43, across two commits. Every restored file is PR #65's, byte-for-byte, from `72216a1` — **no merge, no merge commit, no `main` change, no force-push, nothing written from scratch, nothing mocked.**

### 2.1 `92edfef` — the provisioning fix (48 files)

**The seven Nuxt layers (28 files).** `backend/app/modules/<module>/frontend/` for `case_intelligence`, `ai_case_summary`, `ai_treatment_planning`, `ai_second_review`, `ai_clinical_report`, `clinical_copilot`, `treatment_simulation` — each with `nuxt.config.ts` (declares `components/` with `pathPrefix: false`), `composables/use<Module>.ts` (the API client the warnings named), `components/<Module>Card.vue` (the UI surface), `plugins/slots.client.ts` (registers the card into the **existing** `patient.summary.cards` slot, permission-gated). No host page changed: that slot is already resolved by `backend/app/modules/patients/frontend/pages/patients/[id].vue:215`.

**`frontend/app/utils/aiErrors.ts` (+ `frontend/tests/utils/aiErrors.test.ts`, 6 tests).** Supplies the `aiActionableError` auto-import the warnings named. It maps 503 `<module>_provider_unavailable`, 409 `clinical_context_insufficient` (with the missing/stale list), `dentist_control_required`, 502 contract-validation failure and 403 to distinct actionable messages, then falls back to the shared `errorMessage` chain in `app/utils/error.ts` (which exists on this branch). It surfaces strictly *more* than before — nothing is swallowed, no failure is converted into success.

**`frontend/app/config/permissions.ts` (+30, no deletions).** The permission-key groups the cards gate on: `caseIntelligence`, `aiCaseSummary`, `aiTreatmentPlanning`, `aiSecondReview`, `aiClinicalReport`, `clinicalCopilot`, `treatmentSimulation`. String constants only — no grant, no role change.

**The nine manifests** (`backend/app/modules/*/__init__.py`). Exactly two kinds of line changed, verified by diff: 9× `"auto_install": True` and 7× `"frontend": {"layer_path": "frontend", "navigation": []}`. `auto_install` matters because `ModuleService.reconcile()` creates a record in state `installed` only when the manifest says so; an uninstalled module gets no layer sync **and no mounted router**. `risk_engine` and `dental_3d` take the `auto_install` change only — Risk Engine's UI ships as `RiskEngineCard.vue` **inside the dental_3d layer** (slot id `dental_3d.patient.summary.cards.risk-engine`, permission `risk_engine.read`), which is why it correctly has no layer of its own. **`role_permissions` and `get_permissions()` are untouched in all nine** — a diff grep for `role_permissions|dentist|hygienist|assistant|receptionist|get_permissions` over the manifest changes returns 0 hits.

**The three routers' `LLMConfigError` branch** (`ai_case_summary`, `ai_second_review`, `ai_treatment_planning`, +36/−4 total). Provider misconfiguration now answers `503 {"code": "<module>_provider_unavailable", "message": ...}`, mirroring `clinical_copilot` and `ai_clinical_report`, which already did. This is the contract `aiActionableError`'s primary branch reads; without it, an unconfigured local Ollama surfaced as a generic 502 *"response failed contract validation"* — a misleading diagnosis of a deployment state. Fail-closed behaviour is unchanged: nothing is stored, nothing is faked, the error is more accurate than before.

**The Ollama runtime fix** (`backend/app/core/llm/ollama_provider.py`, `openai_provider.py`, `factory.py`, `backend/app/config.py`, + `backend/tests/test_ollama_provider_url.py`, 7 tests). `OLLAMA_BASE_URL=http://host.docker.internal:11434` — the natural deployment value, and the one `.env.example` documents — used to make the OpenAI-compatible client target `POST /chat/completions`, which Ollama answers with a plain-text `404 page not found`, so **every** generation failed regardless of model availability. The base is now anchored at `/v1` and accepts every spelling (`…:11434`, `…:11434/`, `…:11434/v1`, `…:11434/v1/`, LAN IPs). An empty/whitespace override no longer raises at factory time. `COPILOT_TIMEOUT_SECONDS` (default 120) bounds one inference call so a stalled Ollama cannot hang the HTTP request on the SDK's very long default.

### 2.2 `dd73f5b` — following the change through the suite and the catalogs (3 files)

* `backend/tests/test_ai_clinical_report.py` and `backend/tests/modules/dental_3d/test_api.py` each pinned `manifest.auto_install is False`; both now assert `True`, with PR #65's own explanatory comments. These are assertion updates that follow an intentional manifest change — **no test was deleted, skipped, xfail'd or weakened**, and neither file differs from base in any other line (verified by diff).
* `docs/modules-catalog.md` is generated by `backend/scripts/generate_catalogs.py` and CI has a `catalog-freshness` job that fails on drift, so it was **regenerated, not hand-edited**: 25 lines change, all of them the nine AI modules (install policy `manual → auto`; frontend-layer column `no → yes` for the seven that ship a layer). `risk_engine` correctly stays `no`. `clinical_copilot`'s dependency list is unchanged, and `periodontogram` is untouched (PR #65 also flips that one; it is not an AI module and is out of this scope).

### 2.3 Deliberately NOT taken from PR #65, with reasons

| Not restored | Why |
| --- | --- |
| `frontend/app/composables/usePermissions.ts` | This branch **already** mirrors the backend's `permission_matches` wildcards, through `~/utils/permissions.isGranted` (committed earlier, with its own tests). PR #65 inlines the same rule. Taking theirs would clobber a passing, tested fix for zero behavioural gain. |
| `clinical_copilot`'s extra `depends: ai_second_review` + `DatabaseSecondReviewReader` wiring (`infrastructure.py`, `service.py`, `router.py`) | Copilot *runtime composition*, not provisioning. Copilot still calls its real endpoints; its second-review stage reports **unavailable** honestly instead of pretending. See §3 — this is the one PARTIAL. |
| `backend/app/main.py` dev-CORS origins, `docker-compose.yml` port defaults, `.env.example`, `backend/Dockerfile` `PYTHONPATH` | Deployment config for a stack that is already running on 3100/8100 here. Changing committed defaults could break a working local setup. The exact `.env` values to check are in §6 instead, and the seeding command in §6 uses `-e PYTHONPATH=/app` so it works with or without the Dockerfile change. |
| `backend/app/seeds/ai_demo_data.py` + `scripts/seed_demo.py` changes | Synthetic demo cases. Out of scope, and no mock data belongs in a verification path. |
| `frontend/modules.json` | A generated artifact: the backend rewrites it on every non-production boot (`processor._sync_frontend_layers`) and CI regenerates it by scanning `backend/app/modules/*/frontend`. Hand-editing it would create a second source of truth. Left alone on purpose — §6 step 4 regenerates it through the sanctioned CLI. |
| `docs/workflows/ai-activation.md`, `docs/events-catalog.md` | The runbook documents the synthetic-seed path and the copilot wiring this branch does not carry, so restoring it would ship partially inaccurate instructions. §6/§7 of this document are the equivalent recipe, scoped to what is actually here. (`events-catalog.md` regenerated identically — its one PR #65 delta came from a `case_intelligence/service.py` line shift that is not part of this scope.) |

---

## 3. PROVISIONING STATUS

"Provisioned" below means code-verified in this repository: the layer exists, the manifest declares it, `collect_layers()` emits the path, Nuxt resolves and auto-imports the composable, the component registers, the slot render site exists, and the endpoints the composable calls are mounted. **Live behaviour additionally requires the local steps in §6 and §7** (modules installed in your existing database + a provider configured).

| Module | Status | Evidence |
| --- | --- | --- |
| Case Intelligence | **PASS** | Layer `case_intelligence/frontend` (4 files); `useCaseIntelligence` exported by `.nuxt/imports.d.ts`; `CaseIntelligenceCard` in `.nuxt/components.d.ts`; slot `patient.summary.cards` · `case_intelligence.read`; calls `GET /api/v1/case_intelligence/patients/{id}` — route exists in `router.py`. Deterministic by design (ADR 0027): **no LLM provider needed**, so this one is verifiable without Ollama. |
| Risk Engine | **PASS** | No layer of its own by design — UI is `dental_3d/frontend/components/RiskEngineCard.vue`, slot `dental_3d.patient.summary.cards.risk-engine` · `risk_engine.read`, actions gated on `risk_engine.generate` / `.review` (`risk-engine-generate`, `risk-engine-accept`, `risk-engine-reject`, `risk-engine-provenance`). 4 routes at `/api/v1/risk_engine/`. Deterministic engine, **no provider needed**. Manifest now `auto_install=True`. |
| Dental 3D | **PASS** | Layer already existed on `main` (21 files) and resolves today; manifest now `auto_install=True` so it installs without an admin click. `Dental3DCard` carries the alignment gate (`dental3d-alignment-review/accept/reject`) and the nerve stage (`dental3d-nerve-run/accept/reject/status/error`). 21 routes at `/api/v1/dental_3d/`. Nerve inference needs `DENTAL_3D_NERVE_INFERENCE_URL` (separate service, not Ollama). |
| AI Case Summary | **PASS** (provisioning) | Layer + `useAICaseSummary` resolved; card actions `ai-case-summary-generate` (`ai_case_summary.generate`), `ai-case-summary-accept` / `-reject` (`ai_case_summary.review`), plus provenance/gaps/review-state/claims. Calls `POST /patients/{id}`, `GET /patients/{id}/latest`, `POST /summaries/{id}/review` — all three exist. Generation is **provider-gated**; misconfiguration now returns the actionable 503. |
| AI Treatment Planning | **PASS** (provisioning) | Layer + `useAITreatmentPlanning` resolved; `ai-treatment-planning-generate` (`ai_treatment_planning.generate`), `-accept` / `-reject` (`ai_treatment_planning.review`), options `ai-plan-option-<id>`, provenance/gaps. Calls `POST /patients/{id}`, `GET /patients/{id}/latest`, `POST /results/{id}/review` — all exist. Provider-gated. |
| AI Second Review | **PASS** (provisioning) | Layer + `useAISecondReview` resolved; `ai-second-review-generate` (`ai_second_review.generate`), `-mark-reviewed` (`ai_second_review.review`), findings, simulation picker. Calls `GET /patients/{id}/latest`, `POST /patients/{id}` (with `simulation_id`), `POST /results/{id}/review`, and reads `GET /api/v1/treatment_simulation/patients/{id}/history` — all exist. Hard gate preserved: without a simulation of a dentist-accepted plan the card shows `ai-second-review-no-simulation` and cannot run. Provider-gated. |
| AI Clinical Report | **PASS** (provisioning) | Layer + `useAIClinicalReport` resolved; `ai-clinical-report-generate` (`ai_clinical_report.generate`), readiness panel, per-section output, limitations, provenance. Calls `GET /patients/{id}/readiness`, `POST /generate` — both exist. Readiness gate is server-side and untouched. Provider-gated. |
| Clinical Copilot | **PARTIAL** | Layer + `useClinicalCopilot` resolved; `clinical-copilot-focus`, `-advise` (`clinical_copilot.use`), context panel, claims, limitations, provenance. Calls `GET /patients/{id}/context`, `POST /advise` — both exist, and `clinical_copilot.read`/`.use` gating is intact. **Partial because** the dentist-reviewed AI Second Review stage of its clinical context stays *unavailable* on this branch: making it visible needs PR #65's `DatabaseSecondReviewReader` wiring (`infrastructure.py`, `service.py`, `router.py`), which is copilot runtime composition and was deliberately not restored (§2.3). The card reports that stage as unavailable — accurate, not fabricated. |
| Treatment Simulation | **PASS** (provisioning) | Layer + `useTreatmentSimulation` resolved; `treatment-simulation-run` (`treatment_simulation.generate`), option selector, checkpoints, meta. Calls `GET /patients/{id}/latest`, `GET /patients/{id}/history`, `POST /patients/{id}` (with `planning_id`), and reads `GET /api/v1/ai_treatment_planning/patients/{id}/latest` — all exist. Hard gate preserved: `requires_accepted_plan`, so without a dentist-accepted plan the card shows `treatment-simulation-no-plan` and cannot run. |

Nothing in the cancelled Dental Radiograph Intelligence phase (Caries, Impacted Tooth, Missing Tooth, Periapical Lesion, Tooth Fracture, Root Canal, Crown/Filling) was added, referenced, or revived.

---

## 4. NUXT RESOLUTION

**All eight `[NUXT_B6005] Could not resolve` warnings are eliminated — and this is proven positively, not just by their absence.**

* A production `npx nuxt build` at `dd73f5b` exits 0 and its full log contains **0** lines matching `B6005|could not resolve|unresolved|cannot resolve`, and **0** lines mentioning any of the eight symbols.
* Nuxt's own generated registry now exports them from their canonical paths (`.nuxt/imports.d.ts`):

```
export { aiActionableError } from '../app/utils/aiErrors';
export { useCaseIntelligence, AvailabilityStatus, CaseSectionPayload, CaseSnapshotPayload } from '../../backend/app/modules/case_intelligence/frontend/composables/useCaseIntelligence';
export { useAICaseSummary, SummaryClaimPayload, AICaseSummaryPayload } from '…/ai_case_summary/frontend/composables/useAICaseSummary';
export { useAITreatmentPlanning, PlanningStepPayload, TreatmentOptionPayload, AITreatmentPlanningPayload } from '…/ai_treatment_planning/frontend/composables/useAITreatmentPlanning';
export { useAISecondReview, SecondReviewFindingPayload, AISecondReviewPayload, SimulationOptionPayload } from '…/ai_second_review/frontend/composables/useAISecondReview';
export { useAIClinicalReport, ClinicalStageStatusPayload, AdvisoryClaimPayload, AIClinicalReportPayload, ReportReadinessPayload } from '…/ai_clinical_report/frontend/composables/useAIClinicalReport';
export { useClinicalCopilot, CopilotFocus, ClinicalStageStatePayload, ClinicalCopilotContextPayload, ClinicalCopilotAdvisoryPayload } from '…/clinical_copilot/frontend/composables/useClinicalCopilot';
export { useTreatmentSimulation, SimulationCheckpointPayload, TreatmentSimulationPayload, AcceptedPlanView } from '…/treatment_simulation/frontend/composables/useTreatmentSimulation';
```

* `.nuxt/components.d.ts` registers all seven AI cards plus `RiskEngineCard`.
* Running the **real** `collect_layers()` from `frontend_layers.py` against the real module classes with the container's path settings (`DENTORA_MODULE_PKG_ROOT`, `DENTORA_MODULE_LAYERS_MOUNT=/module_layers`) emits exactly the eight paths the warnings named:

```
case_intelligence       /module_layers/case_intelligence/frontend
dental_3d               /module_layers/dental_3d/frontend
ai_case_summary         /module_layers/ai_case_summary/frontend
ai_treatment_planning   /module_layers/ai_treatment_planning/frontend
ai_second_review        /module_layers/ai_second_review/frontend
ai_clinical_report      /module_layers/ai_clinical_report/frontend
clinical_copilot        /module_layers/clinical_copilot/frontend
treatment_simulation    /module_layers/treatment_simulation/frontend
```

Those are the same strings Nuxt was failing to resolve, now backed by files.

---

## 5. TEST RESULTS

### CODE VERIFIED (run in this environment, at `dd73f5b`)

| Check | Command | Result |
| --- | --- | --- |
| Frontend production build | `npx nuxt build` | **EXIT 0**, 0 B6005, 0 "Could not resolve" |
| Frontend typecheck | `npx nuxt typecheck` | **EXIT 0**, 0 `error TS` |
| Frontend unit/component tests | `npx vitest run` | **54 files / 334 tests pass**, 0 unhandled errors (was 53/328 before this mission; +1 file, +6 tests from the restored `aiErrors` suite) |
| Frontend lint (31 restored files) | `eslint <28 layer files + aiErrors.ts + permissions.ts + aiErrors.test.ts>` | **EXIT 0**, zero output |
| Backend: Ollama URL/timeout regression | `pytest tests/test_ollama_provider_url.py` | **7 passed** |
| Backend: layer discovery + `modules.json` writer | `pytest tests/test_frontend_layers.py` | **7 passed** |
| Backend: manifest contract | `pytest tests/test_manifest_validator.py` | **7 passed**, including `test_every_shipped_module_passes_validation` with all nine changed manifests |
| Backend: the two updated assertions | `pytest …::test_manifest_declares_read_and_dentist_generation …::test_module_discovered_with_expected_manifest` | **2 passed** |
| Backend: catalog freshness (CI job) | `python scripts/generate_catalogs.py --check` | **EXIT 0** (no drift) |
| Backend: syntax of every changed file | `python -m py_compile` × 17 | **all compile** |
| Provisioning chain | `collect_layers()` over the real module classes | **8 layer entries**, exact container paths (§4) |
| RBAC untouched | diff grep over the nine manifests | **0** hits for `role_permissions`, any role name, or `get_permissions` |

### NOT RUN HERE — LOCAL RUNTIME REQUIRED

| Check | Why it could not run here |
| --- | --- |
| The DB-backed backend suite (`tests/test_ai_clinical_report.py` beyond the manifest test, `tests/modules/dental_3d/test_api.py` API tests, `test_module_service.py`, `test_cli_modules.py`, all AI module API tests) | Needs a live PostgreSQL and the app-lifespan fixtures from `tests/conftest.py`. This sandbox has no database and no Docker daemon. Two tests in `dental_3d/test_api.py` (`test_agent_tool_registered`, `test_agent_tool_returns_scene_for_own_clinic`) fail/error **only** under the `--noconftest` run used here, because the agent tool registry is populated by the app lifespan and `db_session` needs a database; `test_agent_tool_registered` is byte-identical to base, so that is an environment artifact, not a regression. |
| Playwright E2E (`frontend/playwright.config.ts`) | Needs a browser plus the full running stack (frontend 3100, backend 8100, db, Ollama). |
| Anything about the live AI runtime: provider reachability, model output, golden-path progression, doctor-approval persistence | Requires your Docker Desktop, your database, your browser and your Ollama. |

Backend dependency note: this sandbox has no Python environment for the backend (`fastapi` was absent; `pip` is PEP-668 blocked). A throwaway venv was created at `/tmp/be` with the subset needed for the unit-level tests above. It is outside the repository and is not part of any commit.

---

## 6. USER MUST RUN LOCALLY

PowerShell, from the repository root (the directory holding `docker-compose.yml`). Copy/paste in order. **No image rebuild is required** — the frontend container bind-mounts `./frontend:/app` and `./backend/app/modules:/module_layers:ro`, so the restored files are visible to it the moment they are on your disk.

### 6.1 Get the fix onto your disk

```powershell
git fetch origin arena/01a091f7-dentora-clinic
git checkout arena/01a091f7-dentora-clinic
git rev-parse HEAD
Test-Path backend\app\modules\case_intelligence\frontend\composables\useCaseIntelligence.ts
Test-Path frontend\app\utils\aiErrors.ts
```
*Checks:* your working tree actually contains the canonical files.
*PASS:* HEAD is the branch tip; both `Test-Path` calls print `True`.
*FAIL:* `False` means the checkout did not happen — every later step will look broken. Do not continue.

### 6.2 Clear the stale Nuxt cache that produced the warnings

```powershell
Remove-Item -Recurse -Force frontend\.nuxt -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force frontend\.output -ErrorAction SilentlyContinue
```
*Checks:* removes the auto-import registry cached from the tree that had the layers. Nuxt regenerates it.
*PASS:* no output. *FAIL:* a file-lock error means the dev container is holding it — run `docker compose stop frontend` first, then repeat.

### 6.3 Install the nine modules in your **existing** database

This step is not optional and is the one most likely to be missed. `ModuleService.reconcile()` only creates a record in state `installed` when **no record exists yet**; your database was created before activation, so these nine already exist as `uninstalled`, and refreshing `auto_install` does **not** promote them. An uninstalled module gets no layer sync *and no mounted router*.

```powershell
docker compose ps
docker compose exec backend python -m app.cli modules list
$mods = "case_intelligence","dental_3d","risk_engine","ai_case_summary","ai_treatment_planning","ai_second_review","ai_clinical_report","clinical_copilot","treatment_simulation"
foreach ($m in $mods) { docker compose exec backend python -m app.cli modules install $m }
docker compose exec backend python -m app.cli modules status
docker compose exec backend python -m app.cli modules restart
```
*Checks:* `ps` — frontend/backend/db healthy. `modules list` — the nine appear. Each `install` schedules the module **and every uninstalled transitive dependency** in topological order. `modules restart` terminates the backend so Docker respawns it and `PendingProcessor` applies the pending installs, then `_sync_frontend_layers()` rewrites `modules.json`.
*PASS:* each install prints `Scheduled for install on next restart:` with a list, or `<name> is already installed.`; after the restart, `docker compose exec backend python -m app.cli modules list` shows all nine as `installed`; `docker compose logs --tail 50 backend` shows no `Pending operation for <name> … failed`.
*FAIL:* `Install blocked: …` (exit 3) means a dependency is not installable — read the message. A module in state `error` means its install hook/migration failed: `docker compose logs backend | Select-String "<module>"`, and `python -m app.cli modules doctor` for a diagnosis. If the nine stay `uninstalled`, the cards cannot appear and their routes will 404.

Equivalent UI path: **Settings → Modules** (`/settings/modules`) → Install for each of the nine.

### 6.4 Regenerate `frontend/modules.json` and confirm the layers are listed

```powershell
docker compose exec backend python -m app.cli modules sync-frontend
docker compose exec frontend sh -c "grep -o '/module_layers/[a-z_0-9]*/frontend' /app/modules.json | sort"
```
*Checks:* the generator writes the layer list from **installed** modules; the second command shows what Nuxt will `extends`.
*PASS:* the eight paths from §4 are all present (`case_intelligence`, `dental_3d`, `ai_case_summary`, `ai_treatment_planning`, `ai_second_review`, `ai_clinical_report`, `clinical_copilot`, `treatment_simulation`). `risk_engine` is correctly absent — its card ships in the `dental_3d` layer.
*FAIL:* missing AI paths ⇒ the modules are not `installed` (back to 6.3), or `ENVIRONMENT=production` in the backend's env (the sync deliberately no-ops in production because layers are baked into the image).

### 6.5 Prove the exact files from the warnings resolve **inside the running container**

```powershell
docker compose exec frontend sh -c 'for f in case_intelligence/composables/useCaseIntelligence ai_case_summary/composables/useAICaseSummary ai_treatment_planning/composables/useAITreatmentPlanning ai_second_review/composables/useAISecondReview ai_clinical_report/composables/useAIClinicalReport clinical_copilot/composables/useClinicalCopilot treatment_simulation/composables/useTreatmentSimulation; do if [ -f "/module_layers/$f.ts" ]; then echo "OK      $f.ts"; else echo "MISSING $f.ts"; fi; done; for m in case_intelligence ai_case_summary ai_treatment_planning ai_second_review ai_clinical_report clinical_copilot treatment_simulation; do for k in components plugins/slots.client.ts nuxt.config.ts; do :; done; done; if [ -f /app/app/utils/aiErrors.ts ]; then echo "OK      app/utils/aiErrors.ts"; else echo "MISSING app/utils/aiErrors.ts"; fi'
```
*Checks:* the precise paths Nuxt reported as unresolvable, tested in the container that reported them.
*PASS:* seven `OK …/use<Module>.ts` lines plus `OK app/utils/aiErrors.ts`, and no `MISSING`.
*FAIL:* `MISSING` ⇒ the bind mount is not seeing your checkout (wrong compose project directory, or you are on a different branch than 6.1 verified).

### 6.6 Restart the frontend and prove the warnings are gone

```powershell
docker compose restart frontend
Start-Sleep -Seconds 45
docker compose logs --since 5m frontend | Select-String -Pattern "NUXT_B6005","Could not resolve"
docker compose logs --since 5m frontend | Select-String -Pattern "error","ERROR" | Select-Object -First 10
docker compose ps
```
*Checks:* a cold Nuxt start with the layers present.
*PASS:* the first `Select-String` prints **nothing at all**; the frontend is `healthy`; the Vite/Nuxt startup completes (`✔ Built`/`Nuxt Nitro server built` or the dev-ready line).
*FAIL:* any `NUXT_B6005` line ⇒ compare its path with 6.4/6.5; a path listed in `modules.json` but missing on disk means 6.1/6.2 were not effective. Other `ERROR` lines are a different problem — send them as-is.

### 6.7 Backend health and the active-module list

```powershell
curl.exe http://localhost:8100/health
$tok = (curl.exe -s -X POST http://localhost:8100/api/v1/auth/login -d "username=YOUR_EMAIL" -d "password=YOUR_PASSWORD" | ConvertFrom-Json).access_token
curl.exe -s http://localhost:8100/api/v1/modules/-/active -H "Authorization: Bearer $tok"
```
*Checks:* backend up; the module registry considers the nine active. Login is **form-encoded** (`OAuth2PasswordRequestForm`) and rate-limited to 5/minute, so do not retry in a loop.
*PASS:* `/health` returns a 200 JSON body; the token is non-empty; `/-/active` lists all nine AI modules.
*FAIL:* empty token ⇒ wrong credentials, or 429 from the rate limiter (wait a minute). A module missing from `/-/active` ⇒ still not installed (6.3).

### 6.8 Ollama reachability, from the host **and** from inside the backend container

```powershell
curl.exe http://localhost:11434/api/tags
docker compose exec backend python -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://host.docker.internal:11434/api/tags',timeout=10))['models'][0]['name'])"
docker compose exec backend python -c "from app.core.llm.factory import get_provider;p=get_provider('ollama');print('base_url =',p._base_url);print('timeout  =',p._timeout)"
```
*Checks:* (1) Ollama is up on the host and which models are pulled; (2) the **backend container** can reach it — this is the hop that actually matters, and it is the one the `/v1` anchoring fix repairs; (3) the provider resolves to the OpenAI-compatible base and carries the bounded timeout.
*PASS:* (1) a JSON list of your models; (2) a model name printed; (3) `base_url = http://host.docker.internal:11434/v1/` and `timeout = 120.0`.
*FAIL:* (2) hanging or `URLError` ⇒ Ollama is not listening on an interface reachable from the container (`OLLAMA_HOST=0.0.0.0` on the Windows side, or use your LAN IP in `OLLAMA_BASE_URL`). (3) a base_url **without** `/v1/` ⇒ the backend is running pre-fix code: confirm 6.1 and that the backend container restarted (`docker compose restart backend`).

### 6.9 Provider selection and your `.env`

```powershell
Select-String -Path .env -Pattern "COPILOT_PROVIDER_DEFAULT|OLLAMA_BASE_URL|COPILOT_MODEL_CHAT_OLLAMA|OPENAI_API_KEY|API_BASE_URL|ALLOWED_ORIGINS|ENVIRONMENT"
curl.exe -s http://localhost:8100/api/v1/copilot/settings -H "Authorization: Bearer $tok"
```
*Checks:* the generation endpoints (case summary, treatment planning, second review, clinical report, copilot advise) route through the provider configured per clinic. Deterministic modules (Case Intelligence, Risk Engine, Dental 3D geometry) need no provider.
*PASS:* `ENVIRONMENT=development`; `API_BASE_URL=http://localhost:8100`; `ALLOWED_ORIGINS` contains `http://localhost:3100` (your browser origin — without it every browser→backend call is CORS-blocked); provider is `ollama` with `OLLAMA_BASE_URL` set, **or** `openai` with `OPENAI_API_KEY` set.
*FAIL:* provider `openai` with no key ⇒ the endpoints now return `503 {"code":"<module>_provider_unavailable"}` and the card says *"AI provider unavailable: …"* — that is the fix working, not a new bug. Switch the provider in **Settings → Copilot** (`PATCH /api/v1/copilot/settings`) or in `.env` and restart the backend.

### 6.10 Backend tests (the ones this sandbox could not run)

```powershell
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests/test_ollama_provider_url.py tests/test_frontend_layers.py tests/test_manifest_validator.py -q
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests/test_ai_clinical_report.py tests/modules/dental_3d -q
docker compose exec -e PYTHONPATH=/app backend python -m pytest -q
```
*Checks:* the provisioning contract, the two updated manifest assertions with a real database, then the whole suite. `-e PYTHONPATH=/app` is what PR #65's `backend/Dockerfile` sets permanently; passing it inline works either way.
*PASS:* all green; `test_every_shipped_module_passes_validation`, `test_manifest_declares_read_and_dentist_generation` and `test_module_discovered_with_expected_manifest` included.
*FAIL:* a red `auto_install` assertion means the tree is not the one from 6.1. Anything else red is pre-existing or environment-related — capture the output rather than assuming this change caused it.

Optional, only if you want PR #65's two companion suites (they are **not** on this branch — the 503-contract suite and the golden-path suite need a live DB):
```powershell
git fetch origin refs/pull/65/head
git checkout FETCH_HEAD -- backend/tests/test_ai_provider_unavailable_states.py backend/tests/test_golden_path_ai_activation.py
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests/test_ai_provider_unavailable_states.py -q
```

### 6.11 Frontend tests, typecheck, lint and build on your machine

```powershell
cd frontend
npm ci
python -c "import json,os;from pathlib import Path;r=Path('..').resolve();ms=r/'backend/app/modules';e=[{'name':p.parent.name,'path':str((p.parent/'frontend').resolve())} for p in sorted(ms.glob('*/frontend'))];Path('modules.json').write_text(json.dumps({'layers':[x['path'] for x in e],'modules':e,'version':1},indent=2))"
npm run typecheck
npx vitest run
npm run build
cd ..
```
*Checks:* the same four gates CI runs. The Python line regenerates `modules.json` with **host** paths — required for a non-Docker run, because the committed file holds container paths and lists only 20 of the layers. This is exactly what `.github/workflows/ci.yml` does in its *"Generate modules.json with host paths"* step.
*PASS:* typecheck exit 0; **54 files / 334 tests** pass; build exit 0 with no `NUXT_B6005` line.
*FAIL:* `ReferenceError: use<Module> is not defined` or `Cannot find name …` in tests/typecheck ⇒ `modules.json` was not regenerated (rerun the Python line). Restore the committed file afterwards with `git checkout -- frontend/modules.json`.

---

## 7. BROWSER CHECKLIST

Log in as a **dentist** (the review/approval permissions are dentist-only for the AI modules; an admin has `*` on some and read-only on others — see the RBAC table below). Open a patient file: **Patients → open a patient → Summary tab**. Every card below appears in that Summary through the `patient.summary.cards` slot, in `order`, and only if your role holds its permission. DevTools → Network, filtered to `api/v1`, is the companion for every step.

RBAC as shipped (unchanged by this fix): `ai_case_summary` admin=read,generate · dentist=read,generate,**review** · hygienist=read · assistant=read · receptionist=none. `ai_treatment_planning` same shape. `ai_second_review` admin=read · dentist=read,generate,**review** · hygienist=read. `ai_clinical_report` admin=read · dentist=read,generate · hygienist=read · assistant=none. `clinical_copilot` admin=read · dentist=read,**use** · hygienist=read · assistant=none. `treatment_simulation` admin=read · dentist=read,generate · hygienist=read. `risk_engine` admin=read,generate · dentist=read,generate,**review**. `case_intelligence` admin=`*` · dentist/hygienist/assistant=read · receptionist=none. `dental_3d` admin=`*` · dentist=`*` · hygienist=read,write · assistant=read.

| # | Module | Navigate / click | Real processing that must happen | Visible proof of success | What failure looks like | Where to look |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **Case Intelligence** | Patient → Summary. No click needed: the card loads on mount (`case-intelligence-card`). | `GET /api/v1/case_intelligence/patients/{id}` builds the deterministic evidence snapshot server-side. No LLM involved. | `case-intelligence-version` shows `Snapshot v<N> · <M> tracked sections`, and one tile per section (`case-section-<name>`) with a status (`available` / `not_available` / `invalid_or_stale`) and an evidence count. | `case-intelligence-error` with a message, or `case-intelligence-empty` ("No case snapshot available yet"). A 404 means the module is not installed (6.3). | Network: that GET's status + body. Backend log for `case_intelligence`. |
| 2 | **Dental 3D** | Same page, `dental3d-card`. Upload a CBCT/DICOM (`dental3d-mesh-upload`), then run patient-space alignment and **review** it: `dental3d-alignment-review` → `-accept` / `-reject`. Then the nerve stage: `dental3d-nerve-toggle` → `dental3d-nerve-run` → `-accept` / `-reject`. | Mesh ingestion + registration, then nerve inference against the external inference service (`DENTAL_3D_NERVE_INFERENCE_URL`). | `dental3d-mesh-count` > 0; alignment review state changes to accepted; `dental3d-nerve-status` progresses and `dental3d-nerve-counts` / `-near` show numbers; `dental3d-nerve-review-state` = accepted. | `dental3d-error`, or `dental3d-nerve-error` / `dental3d-nerve-model-failure`. Nerve failures are usually the inference service URL/token, **not** Ollama. | Network: `/api/v1/dental_3d/...` calls; backend log; inference-service log. |
| 3 | **Risk Engine** | Same page, `risk-engine-card` → **Generate** (`risk-engine-generate`, needs `risk_engine.generate`) → then **Accept** / **Reject** (`risk-engine-accept` / `-reject`, needs `risk_engine.review`). | `POST /api/v1/risk_engine/patients/{id}` runs the deterministic risk engine over the accepted case snapshot / 3D evidence. No LLM. | `risk-map-status` populated and one `risk-factor-<id>` tile per factor, with `risk-engine-provenance` showing the evidence it used. Accepting persists the dentist's decision. | `risk-engine-error`, or `risk-engine-empty`. If Generate is missing/disabled, your role lacks `risk_engine.generate`. | Network: the POST's status/body; whether Accept persists (reload the page — the accepted state must survive). |
| 4 | **AI Case Summary** | Same page, `ai-case-summary-card` → **Generate** (`ai-case-summary-generate`, needs `ai_case_summary.generate`) → read claims → **Accept** or **Reject** (`ai-case-summary-accept` / `-reject`, needs `ai_case_summary.review`). | `POST /api/v1/ai_case_summary/patients/{id}` sends redacted CaseSnapshot input to the configured LLM provider, validates the response against the module contract, and persists it. | Claims render as `ai-case-summary-claim-<id>` with `ai-case-summary-provenance` (which evidence each claim came from) and `ai-case-summary-gaps`; `ai-case-summary-review-state` changes after Accept/Reject and survives a reload. | `ai-case-summary-error`. Read the text: *"AI provider unavailable: …"* = provider config (6.9); *"response failed contract validation and was discarded. No result was stored."* = the model output did not meet the contract (502) — a real refusal, not a UI bug; *"Clinical readiness gate not satisfied. Missing or stale: …"* = the server-side gate (409) blocked generation until the underlying data exists. | Network: the POST's status + `detail.code`. Backend log for `ai_case_summary` and the provider call. |
| 5 | **AI Treatment Planning** | Same page, `ai-treatment-planning-card` → **Generate** (`ai-treatment-planning-generate`) → inspect options `ai-plan-option-<id>` → **Accept** / **Reject** (`ai-treatment-planning-accept` / `-reject`, `review` permission). | `POST /api/v1/ai_treatment_planning/patients/{id}` → provider generation → contract validation → persisted plan with options and provenance. | Options with `ai-treatment-planning-provenance` and `-gaps`; review state persists across reload. **Accepting a plan is the gate for step 6.** | `ai-treatment-planning-error` with the same three message families as step 4. | Network + backend log for `ai_treatment_planning`. |
| 6 | **Treatment Simulation** | Same page, `treatment-simulation-card`. Pick the accepted option (`treatment-simulation-option`) → **Run** (`treatment-simulation-run`, needs `treatment_simulation.generate`). | Reads `GET /api/v1/ai_treatment_planning/patients/{id}/latest`, enforces `requires_accepted_plan`, then `POST /api/v1/treatment_simulation/patients/{id}` with `planning_id`. | `treatment-simulation-meta` plus one `treatment-simulation-checkpoint-<id>` per checkpoint; history via `GET /patients/{id}/history`. | `treatment-simulation-no-plan` — *"No dentist-accepted AI treatment plan available"* — means step 5 was not **accepted** (generating is not enough). This gate is intended; do not work around it. `treatment-simulation-error` otherwise. | Network: the planning `latest` GET must return an accepted plan before the POST will succeed. |
| 7 | **AI Second Review** | Same page, `ai-second-review-card`. Choose the simulation (`ai-second-review-simulation`) → **Generate** (`ai-second-review-generate`) → **Mark reviewed** (`ai-second-review-mark-reviewed`, needs `ai_second_review.review`). | Reads `/api/v1/treatment_simulation/patients/{id}/history`, then `POST /api/v1/ai_second_review/patients/{id}` with `simulation_id`; the provider reviews the accepted plan + simulation; the dentist's review is persisted via `POST /results/{id}/review`. | `ai-second-review-banner`, findings as `ai-second-review-finding-<id>`, `-gaps`, and `ai-second-review-state` reflecting the dentist review. | `ai-second-review-no-simulation` — *"A treatment simulation of an accepted plan is required before a second review can run"* — means step 6 has not run. `ai-second-review-error` otherwise (same three families; a 409 string detail is a safety/state conflict and is surfaced verbatim). | Network: the simulation `history` GET, then the POST's status/`detail.code`. |
| 8 | **AI Clinical Report** | Same page, `ai-clinical-report-card`. Check `ai-clinical-report-readiness` first → **Generate** (`ai-clinical-report-generate`, needs `ai_clinical_report.generate`). | `GET /api/v1/ai_clinical_report/patients/{id}/readiness` evaluates the server-side readiness gate; `POST /api/v1/ai_clinical_report/generate` composes the report from the reviewed chain (copilot + second review). | One `ai-clinical-report-section-<name>` per section, with `ai-clinical-report-limitations` and `-provenance`. | `ai-clinical-report-empty`, or readiness showing unmet prerequisites (that is the gate working — complete steps 4–7 rather than bypassing it), or `ai-clinical-report-error`. | Network: the readiness GET tells you exactly which prerequisite is missing. |
| 9 | **Clinical Copilot** | Same page, `clinical-copilot-card`. Pick a focus (`clinical-copilot-focus`) → **Advise** (`clinical-copilot-advise`, needs `clinical_copilot.use`). | `GET /api/v1/clinical_copilot/patients/{id}/context` assembles the guarded clinical context, then `POST /api/v1/clinical_copilot/advise` runs the Clinical Safety Governor over the provider output. | `clinical-copilot-context` showing the per-stage states, advisory claims `clinical-copilot-claim-<i>`, `clinical-copilot-limitations` and `-provenance`. | `clinical-copilot-error` — including *"Clinical Copilot advisories are restricted to dentist accounts"* (`dentist_control_required`) if you are logged in as a non-dentist, which is the safety architecture, not a bug. **Expected on this branch:** the AI Second Review stage of the context reads *unavailable*, because PR #65's `DatabaseSecondReviewReader` wiring was deliberately not restored (§2.3). Everything else must work. | Network: the context GET (stage states) and the advise POST. Backend log for `clinical_copilot`. |

**Golden path, in order, without bypassing a single gate:** CBCT/DICOM upload → patient-space alignment → **accept** alignment (2) → Dental 3D scene → nerve run → **accept** nerve/risk evidence (2) → Risk Engine generate → **accept** risk (3) → Case Intelligence snapshot present (1) → AI Case Summary generate → **dentist accept** (4) → AI Treatment Planning generate → **dentist accept** (5) → Treatment Simulation run on the accepted option (6) → AI Second Review generate → **mark reviewed** (7) → AI Clinical Report readiness green → generate (8) → Clinical Copilot advise (9).

If a step refuses, the refusal is the safety architecture doing its job: each gate (`requires_accepted_plan`, the second-review simulation requirement, the clinical-report readiness gate, dentist-control on copilot) is server-side and was **not** weakened by this change.

**Known cosmetic limitation, unchanged from the canonical implementation:** all seven AI cards render hardcoded English strings — they contain zero `t()` calls, so they do not follow the app's five locales (default `ar`). The rest of the patient file is translated. Localising them means adding keys to five locale files and rewriting seven cards; that is a separate change and was not invented here.

---

## 8. GIT

| Item | Value |
| --- | --- |
| Branch | `arena/01a091f7-dentora-clinic` (the session branch; no other branch created, checked out, or pushed to) |
| Base | `f1c79ca619d5f8186a52c016cef8606c6d3ce65f` = `main`, **untouched** |
| Commits created by this mission | `92edfef` fix(ai): provision the nine approved AI modules' frontend layers (48 files) · `dd73f5b` test(ai)+docs: follow the manifest activation through the suite and the catalogs (3 files) · plus this document |
| Cumulative diff vs `fcaae25` (the previous mission's tip) | **51 files changed, +2126 / −43** |
| Pushed | Yes — `git push origin arena/01a091f7-dentora-clinic` after each commit; remote tip verified with `git ls-remote` |
| PR #65 | **Not merged, not closed, not modified.** Inspected read-only via `gh pr view/diff` and `git fetch origin refs/pull/65/head` (FETCH_HEAD only — no local branch created, nothing checked out from it except the explicitly listed files) |
| `main` | Not merged into, not modified, not pushed to |
| Force-push / history rewrite | None |
| Database | Not touched — no migration authored, no reset, no drop, no seed run |
| User's stash | `git stash list` was empty; nothing popped, applied, or modified |
| `frontend/modules.json` | **Not overwritten.** Left exactly as committed; §6.4/§6.11 regenerate it through the sanctioned paths |

---

## 9. FINAL VERDICT

**`AI FRONTEND PROVISIONING FIXED — LOCAL RUNTIME VERIFICATION REQUIRED`**

Code-verified here: the seven AI Nuxt layers and `aiErrors.ts` are restored from their only canonical source with provenance; the nine manifests declare `auto_install` and `layer_path`; `collect_layers()` emits exactly the eight container paths the warnings named; Nuxt's generated registry exports all eight symbols and registers all eight cards; typecheck, lint, the full 334-test frontend suite and the production build all pass with **zero** B6005 warnings; the provisioning, manifest and Ollama backend tests pass; and the catalog-freshness CI gate is satisfied.

Not verified here, and not claimable from this environment: that your nine modules are `installed` in your existing database (§6.3 — the single step most likely to block everything else), that your backend container reaches your Ollama (§6.8), that your `.env` has the provider and CORS values the browser needs (§6.9), and that any card produces a real clinical result in your browser (§7). Dental 3D additionally depends on the external nerve-inference service, which is separate from the LLM provider. Clinical Copilot is PARTIAL by decision: its second-review context stage stays unavailable until PR #65's reader wiring is taken, which is a merge decision for you, not for this branch.

Dentora AI is **not** declared operational until you have run §6 and §7 and the results agree.
