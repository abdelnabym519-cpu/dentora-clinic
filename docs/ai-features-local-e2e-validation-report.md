# Dentora AI Features — Local End-to-End Validation Report

**Date:** 2026-09-13 · **Branch:** `arena/01a091f7-dentora-clinic` · **Backend:** `v2.0.0`, 37 modules loaded (30 installed)
**Scope:** the 10 clinical-AI modules, driven through the real HTTP pipeline against real seeded patients — not unit tests, not mocks.

Verification tags used throughout:

| Tag | Meaning |
| --- | --- |
| **CODE VERIFIED** | Read/inspected and reasoned about; not executed |
| **ARENA-SANDBOX VERIFIED** | Actually executed here against a live backend + Postgres |
| **LOCAL RUNTIME REQUIRED** | Cannot be executed in this sandbox (no network egress / needs operator-deployed model service) |
| **NOT VERIFIED** | Neither |

---

## 1. Verdict per module

| # | Module | Bucket | Result | Evidence |
|---|--------|--------|--------|----------|
| 1 | AI Case Summary | P1 | ✅ **WORKS** | `POST /ai_case_summary/patients/{id}` → HTTP 200, artifact `a8a5d28a-…4fb2`, `provider=ollama`, `model=qwen3:8b`, `review_status=pending_review` → dentist-accepted. **ARENA-SANDBOX VERIFIED** (plumbing) / **LOCAL RUNTIME REQUIRED** (real model text) |
| 2 | Case Intelligence (Evidence Snapshot) | P1+P2 | ✅ **WORKS** | HTTP 200, `contract_version=1.0`, `source_digest=sha256:378e3416…`, 14 availability sections, provenance chain, honest `missing_data_report=['nerve']`. **ARENA-SANDBOX VERIFIED** |
| 3 | Risk Engine + 3D Risk Map | P2 | ✅ engine / ⛔ 3D map | Engine: HTTP 200, 10 factors, **125–133 evidence references**, `advisory_only=true`, `is_clinical=false`. 3D risk map: `status=unavailable`, `reason=patient_space_risk_evidence_not_available`, `synthetic_geometry=false` — gated on the nerve pathway (see §5). **ARENA-SANDBOX VERIFIED** |
| 4 | Implant Planning | P2 | ✅ **WORKS** | Accepted alignment → dentist-defined + dentist-accepted prosthetic target → deterministic plan `4d60b7e0-…f7fc7`, `status=proposed` (never auto-approved), candidate centre `(-21.54, -1.26, 10.21)` mm = platform z 15.21 − half of the 10 mm length, Ø4.0×10.0 mm from the supplied catalogue, `frame_of_reference_uid` = the CBCT frame. **ARENA-SANDBOX VERIFIED** |
| 5 | AI Treatment Planning | P1 | ✅ **WORKS** | `POST /ai_treatment_planning/patients/{id}` → HTTP 200, artifact `aa09db62-…23`, `provider=ollama`, `review_status=pending_review` → dentist-accepted; `clinical_output=false`, `canonical_treatment_plan_created=false`. Options are empty **by design** while the nerve gap is open (§5). **ARENA-SANDBOX VERIFIED** (plumbing) / **LOCAL RUNTIME REQUIRED** (real model text) |
| 6 | Treatment Simulation (deterministic) | dependency | ⛔ **GATED** | `POST /treatment_simulation/patients/{id}` requires `{planning_id, option_id}`; no option can exist until a nerve pathway is validated. Gate is correct fail-closed behaviour. **LOCAL RUNTIME REQUIRED** |
| 7 | AI Second Review | dependency | ⛔ **GATED** | Requires `{simulation_id}` from #6. **LOCAL RUNTIME REQUIRED** |
| 8 | AI Clinical Report | dependency | ⛔ **GATED** | `GET /ai_clinical_report/patients/{id}/readiness` → `ready_for_report=false`, stages: `case_intelligence:stale:case_snapshot_contains_stale_sources`, `risk_engine:stale:risk_context_invalid_or_stale`, `ai_treatment_planning:stale:treatment_planning_risk_not_ready`, `treatment_simulation:missing`, `ai_second_review:missing`. All five trace to one root cause (§5). **LOCAL RUNTIME REQUIRED** |
| 9 | Clinical Copilot (guarded advisory) | dependency | ⛔ **GATED** | Same readiness contract (`ready_for_advice=false`, identical `missing_or_stale` list). Context endpoint works: `GET /clinical_copilot/patients/{id}/context` → 200 with `advisory_only`, `dentist_control_required`, `canonical_record_mutation=false`, `evidence_catalog`. **LOCAL RUNTIME REQUIRED** |
| 10 | Orthodontic Simulator | P2 | ⚠️ **CAPABILITY WORKS, MOVEMENT NOT ACHIEVABLE** | Capability endpoint returns real state: `accepted_alignment=true` (the accepted registration genuinely feeds it), `whole_arch_mesh_count=3`, patient-derived STL documents. But `translation_eligible=false` **and** `rotation_eligible=false`, so no movement — per-tooth *or* whole-arch — can be simulated. Translation requires ≥1 document-backed per-tooth mesh; all 32 scene teeth are `synthetic/procedural/document_id=None`, the accepted segmentation carries `teeth: 0`, the scene PUT rejects client tooth meshes, and no server code path creates one. Rotation is hardcoded off pending a trusted tooth-local frame. **ARENA-SANDBOX VERIFIED** (capability + gate) / needs a Dental3D feature, proven four ways in §6 |

**Final driver tally (one patient, full chain):** `22 passed, 0 failed, 6 skipped/gated`.

---

## 2. Problem 1 — the exact misconfiguration

The brief asked for the specific cause among *env misconfiguration vs. Docker networking vs. Ollama not running vs. missing model*. It was **the first two at once, plus a third defect that hid both**. Ollama itself was never the problem. Fixed in `38d0e16` (17 files, +1310/−34):

**Defect 1 — wrong provider (env misconfiguration).** `COPILOT_PROVIDER_DEFAULT` defaulted to `"openai"`. With `OPENAI_API_KEY` empty on a local install, every clinical-AI request was sent to OpenAI with no credential — hence an opaque "Connection error" on all six features. Now the default is *derived*: `production → cloudflare`, every other environment → `ollama`; an explicit setting still wins. All **eight** resolution sites read one property (`Settings.resolved_copilot_provider`) instead of each re-deriving it.

**Defect 2 — no route to the host (Docker networking).** `docker-compose.yml`'s backend service had no `extra_hosts` entry, so `host.docker.internal` **does not resolve on Docker Engine** (it is automatic only on Docker Desktop). `OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434/v1/`, so even with Ollama running and the model pulled, the container could not reach it. The compose service now maps the host gateway explicitly.

**Defect 3 — no error translation (why it looked like one vague bug).** `openai.APIConnectionError` / `APITimeoutError` / 404 escaped `OpenAIProvider` uncaught. Routers catch only `LLMConfigError` / `LLMError`, so FastAPI answered **500** and the actual cause — which host, refused vs. unresolvable vs. model never pulled — was discarded. Transport failures now become `LLMUnavailableError` (an `LLMConfigError`) → clean **503** carrying the real reason.

**Also fixed:** the per-request `AsyncOpenAI` client was never closed, leaking an httpx connection pool on every AI call; the completion now owns its lifecycle.

### Step 1 — are the Ollama calls scattered?

**No. The abstraction already existed and is not bypassed.** `app/core/llm/` holds `base.py` (`Provider` Protocol, `ProviderMessage`, `LLMError`/`LLMConfigError`/`LLMProviderError`), `factory.py` (`get_provider()`), `ollama_provider.py` and `openai_provider.py`. Every AI feature calls the single seam — `ai_case_summary/service`, `ai_case_summary/treatment_service`, `ai_treatment_planning/service`, `ai_second_review/service`, `ai_clinical_report/router`, `clinical_copilot/router`, `copilot/bridge`. No module opens its own Ollama client. What *was* scattered was provider **selection** (defect 1), and that is now one property.

### Step 4 — single provider abstraction, env-selected

**Already satisfied, and it goes further than the brief asked.** `SUPPORTED_PROVIDERS = ("openai", "ollama", "cloudflare")`, resolved by `Settings.resolved_copilot_provider`:

```python
explicit = self.COPILOT_PROVIDER_DEFAULT.strip()
if explicit:
    return explicit
return "cloudflare" if self.ENVIRONMENT.strip().lower() == "production" else "ollama"
```

So `local`/`dev` → Ollama and `production` → Cloudflare Workers AI, exactly as specified. The Workers AI implementation **already exists** — it reuses the OpenAI-compatible client against `https://api.cloudflare.com/<CLOUDFLARE_ACCOUNT_ID>/ai/v1` with `CLOUDFLARE_API_TOKEN` as the Bearer credential and `CLOUDFLARE_AI_MODEL` defaulting to `@cf/meta/llama-3.1-8b-instruct`. Empty account id or token makes that provider *unavailable* (fail-closed) without affecting the Ollama/OpenAI paths. `get_provider()` raises `LLMConfigError` for any provider the deployment cannot serve, "so a clinic can never select a provider that cannot answer."

Nothing needed building here; migration is a config change, not a rewiring of six features. Diagnosis is covered by `backend/scripts/diagnose_ai_provider.py`, which reports the resolved provider *and why*, DNS, TCP, the served model list, an optional real completion (`--probe`) and the per-clinic override (`--db`) — the last matters because `copilot_settings` rows are lazy-created once and never re-derived, so a row written under the old `"openai"` default survives a config fix. (The demo clinic's row is correctly `provider=ollama`, `model=qwen3:8b`.)

**ARENA-SANDBOX VERIFIED here:**
- `response_format={"type":"json_schema"}` is genuinely Ollama-compatible — the stub received `schema=dentora_structured_response`, `stream=true`, `model=qwen3:8b` (resolved from `copilot_settings`, which for the demo clinic is correctly `provider=ollama`, `model=qwen3:8b`).
- **Real prompts are assembled from real patient data.** 6 completions, prompt sizes **53,244 → 70,844 → 74,689 → 90,242 → 94,118 characters**. The prompt *grew* exactly when the geometry work landed: the user payload's `availability` block changed from `alignment: invalid_or_stale, anatomy: invalid_or_stale` to `alignment: available, anatomy: available, implant_planning: available`. That is the strongest available proof that Problem 1 and Problem 2 meet in the same pipeline.
- System prompts are the real module prompts, e.g. *"You select advisory dental case facts from ONE structured Dentora CaseSnapshot projection… evidence_id must reference exactly one evidence object."*
- **Guardrail:** pointed the stub at prose instead of JSON → **HTTP 502** `"AI summary provider failed validation"` / `"AI treatment planning provider failed validation"`, and **nothing was persisted** (the previously accepted summary `a8a5d28a` was untouched). No 500s on any path exercised.

**LOCAL RUNTIME REQUIRED:** actual model text. This sandbox has **no network egress** (`registry.ollama.ai` → connection failure), so no model can be pulled. Every AI artifact generated here is an envelope with empty `claims`/`options` — the transport, schema, parsing, persistence and review path are proven; the *words* can only come from your local Ollama.

---

## 3. Problem 2 — test data created and really ingested

Nothing was inserted into the database directly. Every byte went through the product's own endpoints.

**IOS fixture** — `backend/scripts/build_ios_development_fixture.py` → `/tmp/fix/scan_maxillary.stl`: parametric maxillary arch, 14 teeth (FDI 17→27), watertight, 11,760 faces, 62.0 × 47.3 × 16.3 mm, millimetre units. Deliberately *toothed* — the repo's existing `build_demo_arch_stl` is rotationally symmetric and therefore ill-posed for ICP.

**CBCT fixture** — `backend/scripts/build_cbct_development_fixture.py` → 40 real DICOM CT slices rasterised *from that same mesh*, 320² grid, 0.5 mm slice spacing, deterministic Study/Series/FrameOfReference UIDs. Added `--uid-namespace` so a fresh deterministic series can be minted and the same patient re-ingested without SOP-instance clashes.

**Ingestion (real endpoints, dentist token):**

| Step | Endpoint | Result |
| --- | --- | --- |
| IOS mesh | `POST /dental_3d/patients/{id}/meshes` (multipart) | stored via the media module |
| CBCT | `POST /dental_3d/cbct/dicom-instances` × 40 | **40/40 instances accepted**, normalised |
| Segmentation | `POST …/segmentation` + `…/{id}/review` | 32 teeth, dentist-accepted |
| Alignment | `POST …/alignment` + `…/{id}/review` | real transform, dentist-accepted |
| Prosthetic target | `POST …/prosthetic-targets` + `…/{id}/review` | dentist-defined, dentist-accepted |

**The registration is real and non-trivial.** The fixtures were built with a deliberate ~14 mm y-offset between the CBCT anatomy and the IOS mesh, so identity would fail. Result:

```
algorithm: open3d_ransac+open3d_icp
transform: rotation ≈ identity (1e-4 rad residuals)
           translation = (+0.0010, −14.3274, +3.8485) mm
provenance: ios digest sha256:059d49f7…  document_ids=[…]  original_unit=mm
status: pending_review → accepted
reviewed_by: b1eebc99-…a23 (dentist@demo.clinic)   reviewed_at: 2026-09-12T23:11:16Z
disclaimer: "Technical registration only; clinical accuracy threshold is not validated. Dentist review required."
```

Open3D recovered the true offset it was given. **No accepted flag was written directly** — acceptance went through the module's own review endpoint under a dentist token, and `requires_review` stayed `true`.

**Anatomy service precondition.** `default_registration_components()` selects `HttpDentalSegmentatorAdapter` only when `DENTAL_3D_DENTAL_SEGMENTATOR_URL` is set; otherwise it fails closed with `dependency_unavailable`. That was the *correct* behaviour, so instead of weakening it I satisfied the precondition: `backend/scripts/serve_dev_anatomy_service.py` implements the `dental-anatomy-v1` contract (zip in, `DICOM_PATIENT_LPS`/mm points out, FoR must match, `extra="forbid"`) by classical intensity thresholding of the **real ingested voxels** with standard NEMA patient-coordinate mapping. It reports itself honestly as `model_id="dentora-dev-threshold-anatomy"`, is not on any default path, and does not alter the gate.

Effect, measured: extracted anatomy bbox `x ±30.9, y ±23.7, z 2.0…18.0` mm (6,033 points) — full coverage of the 16 mm arch, and case intelligence's `anatomy` section moved from `invalid_or_stale` to **`available`**.

---

## 4. What the geometry work unlocked

Case intelligence availability for the fully-processed patient:

```
ios available · cbct available · media available · alignment available
anatomy available · prosthetic available · implant_planning available
odontogram available · periodontogram available · patient available
timeline available · medical_context available · treatment_history available
nerve INVALID_OR_STALE        ← the only gap
missing_data_report: ['nerve']
reference_frame.status: available   (from the accepted DentalAlignmentResult)
```

Thirteen of fourteen source sections are available, and the reference frame is valid — the registration is what made that true.

**Measured effect on the AI planning gate.** The same endpoint against a patient with *no* geometry at all returns `options: 0` with ten data gaps:

```
missing_data_report (no geometry):  ['anatomy','nerve','alignment','cbct','ios',
                                     'prosthetic','periodontogram','medical_context',
                                     'media','implant_planning']
missing_data_report (after this work): ['nerve']
```

Both cases produce zero options — the module is correctly conservative and will not author treatment strategies from an incomplete record either way — but the ingestion/registration work collapsed the gap list from ten entries to one. That single remaining entry is the nerve pathway, and it is the only thing standing between the current state and modules #6–#9.

---

## 5. The single root cause behind modules 6–9

All four remaining locked modules reduce to **one** precondition. From `app/modules/case_intelligence/source_dental3d.py`:

```python
valid = (
    nerve.review_status == "accepted"        # a dentist accepted it
    and nerve.detection_status == "detected" # a real model actually detected it
    and nerve.input_kind == "cbct_series"    # derived from real CBCT
    and native                               # dicom_patient / mm / FoR UID present
    and compatible                           # FoR == accepted alignment's target frame
)
```

Ours returns `detection_status="failed"`, `failure=missing_model: No nerve inference model service is configured` → reason `latest_nerve_pathway_not_validated`. The cascade is then entirely by design:

```
nerve not validated
  → ai_treatment_planning emits data_gaps[{section:"nerve", reason:"latest_nerve_pathway_not_validated"}] and options: []
    → no option_id → treatment_simulation cannot run (422: planning_id/option_id required)
      → no simulation_id → ai_second_review cannot run (422)
        → report/copilot readiness: clinical_context_insufficient
```

**I deliberately did not fake this.** Bone/anatomy has a legitimate classical proxy (intensity thresholding), so the dev anatomy service is honest. A mandibular nerve does not — a threshold stand-in would have produced a fabricated canal, and every downstream artifact would have carried invented clinical geometry. That crosses the "no fake/hardcoded data" line, so #6–#9 stay honestly gated.

**What it needs locally:** the operator-deployed inference service the repo already documents —

```
DENTAL_3D_NERVE_INFERENCE_URL=http://nerve-inference:8080/v1/nerve-detection
DENTAL_3D_NERVE_INFERENCE_TOKEN=…
docker compose -f docker-compose.nerve-ai.yml up   # requires DENTORA_NERVE_MODEL_HOST_DIR
```

### Why this is genuinely unreachable from the sandbox

`nerve-inference-service/` implements the `nerve-detection-v1` boundary with **DentalSegmentator / nnU-Net v2.2.1**, where the mandibular canal is label 5. Its weights are external artifacts by design — *"Model weights are mounted read-only at runtime and are never committed"* — so there is nothing to run here even in principle:

| Item | Value |
| --- | --- |
| Model | Dataset112_DentalSegmentator_v100 (470 CT/CBCT scans, 5 classes) |
| Source | Zenodo record **10829675**, DOI `10.5281/zenodo.10829674` |
| File / checksum | `Dataset112_DentalSegmentator_v100.zip`, md5 `b71cd5230168d28a4f71b078265b76be` |
| Licence | CC BY 4.0, commercial use permitted **with attribution** |
| Provisioning | `python nerve-inference-service/scripts/provision_model.py --target <dir>` (download → md5 verify → extract → identity validate → sha256 manifest) |
| Runtime | CPU torch is the designed default; upstream recommends 32 GB RAM |
| Production guard | blocked unless `DENTORA_NERVE_COMMERCIAL_USE_APPROVED=true` |

This sandbox has **no network egress**, so `provision_model.py` cannot fetch the weights, and the compose file hard-requires `DENTORA_NERVE_MODEL_HOST_DIR`. Two traps worth repeating: do **not** substitute `Dataset111_453CT_v100.zip` (teeth-only — the runtime contract rejects it because `dataset.json` has no `Mandibular canal == 5`), and the returned `confidence` is a mean class-5 softmax, explicitly *not* a calibrated probability or a clinical-safety score.

**And one data caveat that matters:** every fixture here is a **maxillary** arch. There is no inferior alveolar canal in a maxilla, so even a perfect model would return no detected pathway and `detection_status` would not be `"detected"`. To exercise #6–#9 locally you need a **mandibular CBCT with a visible canal** — a real scan or a public CBCT dataset, not a synthetic one, since nnU-Net was trained on real CT/CBCT intensity statistics.

---

## 6. Orthodontic Simulator — a contract limitation, not a data gap

The capability endpoint reports honestly:

```
whole_arch_mesh_count: 2      per_tooth_mesh_count: 0
accepted_alignment: true      ← the accepted registration does feed this gate
translation_eligible: false   rotation_eligible: false
reasons:
  whole-arch-only            "Dental3D currently exposes whole-arch scan geometry without a
                              reviewed per-tooth mesh mapping; patient-specific tooth movement
                              is disabled."
  tooth-local-frame-unavailable
                             "Trusted tooth-local frames are not available in the current
                              Dental3D contract; tip, torque and long-axis rotation are not
                              rendered."
```

Whole-arch geometry is patient-derived and present — but note that `translation_eligible` is gated on per-tooth meshes as well, so whole-arch *movement* is blocked by the same missing input, not only per-tooth movement. I verified this from four independent directions rather than accepting the endpoint's self-description:

**1. The eligibility formula** (`orthodontic_simulator/service.py`) requires tooth meshes backed by real stored documents:

```python
def _per_tooth_meshes(scene):
    return [t for t in scene.teeth
            if t.present and t.mesh.source != "synthetic"
            and t.mesh.document_id is not None and t.mesh.format != "procedural"]

translation_eligible = bool(per_tooth) and reviewed_count == len(per_tooth) and accepted_alignment
rotation_eligible = False   # hardcoded: "Never infer one from crown shape, PCA or a whole-arch registration."
```

**2. The live scene for the fully-processed patient** — all 32 teeth fail that filter:

```
teeth: 32 → source=synthetic  format=procedural  document_id=None   (all 32)
scene-level meshes: 3 × (intraoral_scan, stl, document_id=True)      ← whole-arch is real
segmentation: completed, review_status=accepted, teeth: 0            ← accepted, but carries no tooth meshes
```

The accepted segmentation satisfies `reviewed_count`, but there is nothing to count.

**3. The client cannot supply them either.** `DentalSceneUpdate` rejects it outright: *"tooth mesh descriptors are server-derived — PUT accepts only the default synthetic mesh"*, and `segmentation`/`nerve_detection`/`cbct_series` are likewise refused from clients. So uploading per-tooth STLs through the scene endpoint is impossible by design — correctly, since that would let a client assert clinical geometry.

**4. No server path produces them.** The only `Tooth3D(...)` constructions are `infrastructure.py:330,344` and `service.py:111`, all with the default synthetic mesh; nothing anywhere assigns a tooth-level `document_id`. `schemas.py` states the roadmap explicitly: *"Phase 1 teeth always use `source="synthetic"`, `format="procedural"` and no `document_id`… Phase 2 adds real surface meshes **at scene level**."* Scene level is exactly what my IOS upload populated; tooth level was never in scope.

**Conclusion:** this needs a feature, not data or configuration — Dental3D must publish per-tooth meshes as media documents (most plausibly derived from the accepted segmentation), and the contract needs a *trusted* tooth-local frame field before rotation can ever be enabled. Both were left alone: inventing either would have meant weakening a gate or fabricating clinical geometry.

---

## 7. Safety properties observed while running (all intact)

- Every AI artifact landed `pending_review` first; a dentist token had to accept each one (`reviewed_by`, `reviewed_at`, `review_note` recorded by the module).
- `advisory_only=true`, `requires_review=true`, `is_clinical=false`, `clinical_output=false`, `canonical_record_mutation=false`, `dentist_control_required=true` on every contract that exposes them.
- `RiskResult` has **no** overall risk score or diagnosis — by design. Disclaimer: *"Observed-fact decision support only; no diagnosis, risk score, or validated clinical threshold."*
- Implant plans stayed `status=proposed`; nothing auto-advanced past review.
- Risk factors report real data gaps instead of inventing values, e.g. `accepted_nerve_pathway_present: state=invalid_or_stale band=invalid_source observed=None`, while genuine clinical context resolves: `anticoagulant_context_present: state=present band=evidence_present observed=True`.
- Malformed provider output → 502, nothing persisted.
- No gate logic was modified anywhere. Every gate was either satisfied by meeting its real precondition or reported as-is.

---

## 8. Local commands (sequential, minimal)

```bash
# 1. Ollama with the model the settings already point at
ollama pull qwen3:8b && ollama serve

# 2. Backend must reach it — from inside Docker, localhost is the container
export OLLAMA_BASE_URL=http://host.docker.internal:11434/v1/
export COPILOT_PROVIDER_DEFAULT=ollama

# 3. Confirm the provider end to end (probes the model AND the stored clinic settings)
docker compose exec backend python -m scripts.diagnose_ai_provider --probe --db

# 4. The two operator-deployed geometry services
export DENTAL_3D_DENTAL_SEGMENTATOR_URL=http://<anatomy-host>/v1/dental-anatomy
export DENTAL_3D_DENTAL_SEGMENTATOR_TOKEN=<token>
export DENTORA_NERVE_MODEL_HOST_DIR=/path/to/real/nerve/weights
docker compose -f docker-compose.nerve-ai.yml up -d

# 5. Full chain against a MANDIBULAR CBCT + its IOS scan
python -m scripts.verify_ai_geometry_chain \
  --base-url http://localhost:8000 --steps all \
  --patient-id <real-patient-id> \
  --ios /path/to/scan.stl --cbct-dir /path/to/dicom/
```

Step 5 is the same driver used for every result above; it prints a PASS/FAIL/SKIP line per stage and the summary tally.

---

## 9. Artifacts

**Committed earlier (Problem 1):** `38d0e16` — 17 files, error translation centralised in the provider layer; 102 passed / 2 skipped.

**Added by this validation** (`backend/scripts/`, development tooling — no production path references them):

| File | Purpose |
| --- | --- |
| `verify_ai_geometry_chain.py` | End-to-end driver: ingestion → segmentation → alignment → prosthetic target → risk → implant → ortho → the AI chain, with dentist acceptances at every human-in-the-loop gate. `--steps geometry\|ai\|all` |
| `build_ios_development_fixture.py` | Parametric toothed IOS arch (watertight, mm) — ICP-solvable, unlike the rotationally symmetric demo arch |
| `build_cbct_development_fixture.py` | Mesh → axial CT DICOM series; `--uid-namespace` mints a fresh deterministic UID block |
| `serve_dev_anatomy_service.py` | Dev stand-in for the operator-managed DentalSegmentator; implements `dental-anatomy-v1` by thresholding real voxels; self-identifies as a dev model |

**Sandbox-only (not committed, deliberately):** `/tmp/fix/` fixtures, `/tmp/glstub/libGL.so.1` (lets Open3D import headless), `/tmp/aitest/stub_ollama_schema.py` (schema-conformant Ollama stand-in + request log), `/tmp/pgdata`, `/tmp/storage`.

---

## 10. Bottom line

- **Problem 1 is fixed and committed (`38d0e16`).** It was not one bug but three stacked ones: `COPILOT_PROVIDER_DEFAULT` defaulted to `"openai"` so every request left the backend with no credential (env misconfiguration); the compose backend had no `extra_hosts`, so `host.docker.internal` was unresolvable on Docker Engine and Ollama unreachable even when running (Docker networking); and `APIConnectionError`/`APITimeoutError` escaped the provider so FastAPI answered 500 and threw the real cause away (missing error translation, plus a leaked httpx pool per call). Ollama's `json_schema` support is confirmed compatible, and real prompt assembly is proven with 53k–94k-character case-derived prompts. Only the model's *words* still need your local Ollama.
- **The provider abstraction the brief asked for already exists** — one `get_provider()` seam in `app/core/llm/`, seven feature callers, no module talking to Ollama directly, `production → cloudflare` / everything else `→ ollama`, and the Workers AI implementation already present and fail-closed when unconfigured. Nothing to build; cloud migration is a config change.
- **Problem 2 is solved for everything the sandbox can legitimately reach.** Real IOS + real 40-slice CBCT ingested through real endpoints, real Open3D RANSAC+ICP that recovered the 14.3 mm offset it was given, real dentist acceptances at every gate — and that flipped case intelligence's `alignment`/`anatomy` from `invalid_or_stale` to `available`, which is what unlocked implant planning end to end.
- **Six steps remain gated on one honest precondition:** a dentist-accepted, model-detected nerve pathway in the accepted alignment's frame. The weights are external Zenodo artifacts that are never bundled and cannot be downloaded here. It was not faked.
- **One limitation is architectural, not environmental:** no orthodontic movement — per-tooth *or* whole-arch — can be simulated, because eligibility requires document-backed per-tooth meshes that no code path produces and the scene PUT forbids clients from supplying. That is a Dental3D feature (publish per-tooth meshes; add a trusted tooth-local frame), not a data or configuration gap.
