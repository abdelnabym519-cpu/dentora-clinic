# Dentora AI Features — Local End-to-End Validation Report

**Date:** 2026-09-13 · **Branch:** `arena/01a091f7-dentora-clinic` · **Backend:** `v2.0.0`, 37 modules loaded (30 installed)
**Scope:** the clinical-AI modules driven through the real HTTP pipeline against real ingested data — not unit tests, not mocks.

Verification tags used throughout:

| Tag | Meaning |
| --- | --- |
| **CODE VERIFIED** | Read/inspected and reasoned about; not executed |
| **ARENA-SANDBOX VERIFIED** | Actually executed here against a live backend + Postgres |
| **LOCAL RUNTIME REQUIRED** | Cannot be executed in this sandbox (needs a real model / operator-deployed weights) |
| **NOT VERIFIED** | Neither |

---

## 1. Verdict per module

Full-chain run on a fresh synthetic mandibular patient (`1ef900e9-a8c3-4485-97fc-55c76b425f1b`), one command, dentist acceptances at every gate:

**`35 passed, 0 failed, 1 skipped/gated`** — the single gated item is the orthodontic simulator (§6).

| # | Module | Result | Evidence |
|---|--------|--------|----------|
| 0 | **Nerve / IAN detection** | ✅ **WORKS** | `POST /dental_3d/patients/{id}/nerve-detection` → `status=detected`, **2 pathways**, `source=model_inference`, `input_kind=cbct_series`, confidence 0.646 / 0.641, 19 points each, dentist-accepted. Traced by a real algorithm from real voxels (§5). **ARENA-SANDBOX VERIFIED** (classical detector) / **LOCAL RUNTIME REQUIRED** (trained weights in production) |
| 1 | AI Case Summary | ✅ **WORKS** | HTTP 200 → `pending_review` → dentist-accepted. Claims cite real evidence ids and resolve to real scalars, e.g. `nerve → analysis_metadata.confidence_summary.count = 2`, `maximum = 0.646`, `mean = 0.6435`. **ARENA-SANDBOX VERIFIED** (plumbing + grounding) / **LOCAL RUNTIME REQUIRED** (real model selection) |
| 2 | Case Intelligence (Evidence Snapshot) | ✅ **WORKS** | HTTP 200, `contract_version=1.0`, **14/14 sections available**, `missing_data_report` empty, 295 evidence records (289 with resolvable scalar facts), provenance chain. **ARENA-SANDBOX VERIFIED** |
| 3 | Risk Engine + 3D Risk Map | ✅ **BOTH WORK** | Engine: 10 factors, **136 evidence references**, all resolving (`present` ×3, `absent` ×7, **no `not_available`**). 3D risk map: `status=available`, **3 regions** — `nerve-pathway-1` (polyline, 19 pts), `nerve-pathway-2` (polyline, 19 pts), `accepted-implant-1` (cylinder) — in frame `…9303`. Previously `unavailable`. **ARENA-SANDBOX VERIFIED** |
| 4 | Implant Planning | ✅ **WORKS** | Accepted alignment → dentist-defined + dentist-accepted prosthetic target → deterministic plan, candidate `(-22.21, -16.11, 24.50)` mm, `status=proposed` (never auto-approved) → dentist accepted it through `/implant-plans/{id}/review`. **ARENA-SANDBOX VERIFIED** |
| 5 | AI Treatment Planning | ✅ **WORKS — 2 real options** | HTTP 200, `advisory_only=true`, `no_automatic_execution=true`, `canonical_treatment_plan_created=false`, `data_gaps=[]`. Rendered rationale carries the detector's real output: *"Documented basis: **Nerve count: 2; Nerve maximum: 0.646** … Deterministic risk context: **Accepted implant solid intersects accepted nerve centerline: absent; Accepted patient-space mandibular nerve pathway present: present.**"* Previously `options: []`. **ARENA-SANDBOX VERIFIED** |
| 6 | Treatment Simulation (deterministic) | ✅ **UNLOCKED** | HTTP 200 with a real `{planning_id, option_id}`. Contract text: *"Visualization of an accepted advisory plan in existing patient-space evidence only; no biological outcome or geometric treatment result is predicted."* **ARENA-SANDBOX VERIFIED** |
| 7 | AI Second Review | ✅ **UNLOCKED** | HTTP 200 → `pending_review` → dentist decision recorded (`review_status=reviewed`). Output `{"findings": [], "data_gaps": []}` — correct, since no case section is `not_available` any more and the contract forbids inventing gaps. **ARENA-SANDBOX VERIFIED** |
| 8 | AI Clinical Report | ✅ **UNLOCKED** | HTTP 200, `ready_for_report=true`, payload with **6 sections**, `provider=ollama`, `model=qwen3:8b`, `contract_version=1.0`. **ARENA-SANDBOX VERIFIED** (structure) / **LOCAL RUNTIME REQUIRED** (real prose) |
| 9 | Clinical Copilot (guarded advisory) | ✅ **UNLOCKED** | HTTP 200, **2 claims**, each grounded in `allowed_evidence_ids`; `advisory_only`, `dentist_control_required`, `canonical_record_mutation=false`. Claim text self-identifies as stand-in output (§5.4). **ARENA-SANDBOX VERIFIED** |
| 10 | Orthodontic Simulator | ⚠️ **CAPABILITY WORKS, MOVEMENT GATED** | `whole_arch_mesh_count=1`, `per_tooth_mesh_count=0`, `accepted_alignment=true`, `translation_eligible=false`, `rotation_eligible=false`. Genuine architectural gap, re-examined and confirmed in §6 — **left gated deliberately**. **ARENA-SANDBOX VERIFIED** |

Safety properties held throughout: every AI artifact landed `pending_review` first and needed a dentist token; nothing auto-advanced; no gate logic was modified anywhere (§7).

---

## 2. Problem 1 — the exact misconfiguration (fixed in `38d0e16`)

Not one bug but three stacked ones. Ollama itself was never the problem.

**Defect 1 — wrong provider (env misconfiguration).** `COPILOT_PROVIDER_DEFAULT` defaulted to `"openai"`. With `OPENAI_API_KEY` empty on a local install, every clinical-AI request went to OpenAI with no credential — hence an opaque "Connection error" on all six features. The default is now *derived*: `production → cloudflare`, every other environment → `ollama`; an explicit setting still wins. All **eight** resolution sites read one property (`Settings.resolved_copilot_provider`).

**Defect 2 — no route to the host (Docker networking).** The compose backend had no `extra_hosts`, so `host.docker.internal` **does not resolve on Docker Engine** (automatic only on Docker Desktop). `OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434/v1/`, so even a running Ollama with the model pulled was unreachable. The compose service now maps the host gateway explicitly.

**Defect 3 — no error translation (why it looked like one vague bug).** `openai.APIConnectionError` / `APITimeoutError` / 404 escaped `OpenAIProvider` uncaught. Routers catch only `LLMConfigError` / `LLMError`, so FastAPI answered **500** and discarded the real cause. Transport failures now become `LLMUnavailableError` → clean **503** carrying the reason. Also fixed: the per-request `AsyncOpenAI` client was never closed, leaking an httpx pool on every AI call.

### The abstraction the brief asked for already existed

`app/core/llm/` holds `base.py` (`Provider` Protocol, `ProviderMessage`, error hierarchy), `factory.py` (`get_provider()`), `ollama_provider.py`, `openai_provider.py`. Every AI feature calls that single seam; no module opens its own Ollama client. What *was* scattered was provider **selection** (defect 1), now one property. Cloudflare Workers AI is already implemented and fail-closed when unconfigured, so cloud migration is a config change, not a rewiring.

`backend/scripts/diagnose_ai_provider.py` reports the resolved provider *and why*, DNS, TCP, the served model list, an optional real completion (`--probe`) and the per-clinic override (`--db`) — the last matters because `copilot_settings` rows are lazy-created once and never re-derived, so a row written under the old `"openai"` default survives a config fix.

**Verified here:** `response_format={"type":"json_schema"}` is genuinely Ollama-compatible; real prompts are assembled from real patient data (**53,244 → 94,118 characters**, growing exactly when the geometry work landed); pointing the provider at prose instead of JSON yields **502** with nothing persisted.

---

## 3. Problem 2 — test data created and really ingested

Nothing was inserted into the database directly. Every byte went through the product's own endpoints.

**Maxillary fixtures** (`/tmp/fix/`): `build_ios_development_fixture.py` → watertight 14-tooth arch, 11,760 faces, 62.0 × 47.3 × 16.3 mm; `build_cbct_development_fixture.py --anatomy arch_surface` → 40 real DICOM CT slices rasterised from that same mesh, deterministic UIDs. Deliberately *toothed* — the repo's existing `build_demo_arch_stl` is rotationally symmetric and therefore ill-posed for ICP.

**The registration is real and non-trivial.** The fixtures carry a deliberate ~14 mm y-offset, so identity would fail:

```
algorithm: open3d_ransac+open3d_icp
transform: rotation ≈ identity (1e-4 rad residuals)
           translation = (+0.0010, −14.3274, +3.8485) mm
status: pending_review → accepted by dentist b1eebc99-…a23
disclaimer: "Technical registration only; clinical accuracy threshold is not validated. Dentist review required."
```

**Anatomy service precondition.** `default_registration_components()` selects `HttpDentalSegmentatorAdapter` only when `DENTAL_3D_DENTAL_SEGMENTATOR_URL` is set; otherwise it fails closed with `dependency_unavailable`. That was correct behaviour, so instead of weakening it I satisfied the precondition: `serve_dev_anatomy_service.py` implements `dental-anatomy-v1` by classical intensity thresholding of the **real ingested voxels** with standard NEMA patient-coordinate mapping, and self-identifies as `model_id="dentora-dev-threshold-anatomy"`. Effect: 6,033 anatomy points, bbox `x ±30.9, y ±23.7, z 2.0…18.0` mm; case intelligence's `anatomy` section moved `invalid_or_stale → available`.

---

## 4. What unlocked what

Case intelligence availability for the fully-processed mandibular patient:

```
ios available · cbct available · media available · alignment available
anatomy available · prosthetic available · implant_planning available
odontogram available · periodontogram available · patient available
timeline available · medical_context available · treatment_history available
nerve AVAILABLE                       ← was the only gap; see §5
missing_data_report: []               ← was ['nerve']
reference_frame.status: available
```

The dependency chain that had modules 6–9 locked is now satisfied end to end, and each link was met with real data rather than a gate change:

```
real canal voxels  →  detector traces 2 centrelines  →  dentist accepts the pathway
  →  case_intelligence nerve section available  →  risk_engine: all 10 factors resolve,
     risk_map available with 2 nerve polylines + 1 implant cylinder
  →  ai_treatment_planning emits 2 grounded options  →  option_id exists
    →  treatment_simulation runs  →  simulation_id exists
      →  ai_second_review runs  →  report/copilot readiness ready_for_*=true
```

Two further preconditions were satisfied the same way (§5.5): the report/copilot gate also required a complete clinical record, and the risk engine required an *accepted* implant plan before the implant/nerve intersection factor could resolve.

---

## 5. Task A — the nerve gate: how it was satisfied

### 5.1 Path selection (the brief required trying them in order)

| Path | Verdict | Why |
| --- | --- | --- |
| **1. Real pretrained model** | ❌ **Impossible here** | Weight hosts are all unreachable from this sandbox. Egress matrix, measured: pip/PyPI ✅, github.com pages ✅, `raw.githubusercontent.com` ❌, `objects.githubusercontent.com` ❌, Hugging Face ❌, Zenodo ❌, `download.pytorch.org` ❌, grand-challenge ❌, Synapse ❌. `nerve-inference-service/scripts/provision_model.py` cannot fetch `Dataset112_DentalSegmentator_v100.zip`. |
| **2. Classical non-ML detector** | ✅ **Adopted** | Produced real, geometry-dependent results and — the brief's condition — correctly reports *no detection* on canal-free input. Proof in §5.3. |
| **3. Documented operator service** | ✅ **Also delivered** | The production path is unchanged and fully documented (§5.6). The dev detector sits behind the *same* `nerve-detection-v1` contract, so swapping in real weights is a URL change. |

### 5.2 The detector — `backend/scripts/serve_dev_nerve_service.py`

A classical inferior-alveolar-canal tracer. No trained weights, no hardcoded geometry, no absolute HU assumptions (CBCT intensities are uncalibrated, so every threshold is derived from the volume's own histogram):

1. **3-class Otsu** on the HU histogram → background / cancellous / cortical thresholds; bone mask hole-filled.
2. **Frangi multi-scale vesselness** (σ = 1.0, 1.5, 2.2 mm) on the bone-inverted image, resampled to 0.9 mm isotropic.
3. **Hysteresis thresholding** (Canny-style): seed at 0.45 × the 99.5th-percentile response, connect at 0.12 ×, so a long canal is not fragmented by one hot peak.
4. **Geometric acceptance tests**, all of which must pass: traced length ≥ 12 mm, tubularity ≥ 3.0, lumen radius 0.6–3.0 mm, and ≥ 60 % of a surrounding annulus at bone density (a canal is *enclosed* in bone).
5. **PCA-slab centreline** → patient LPS millimetres via the NEMA mapping; side assigned by the sign of x; confidence derived from the measured margins, not asserted.

It self-identifies honestly: `model_id="dentora-dev-classical-ian-vesselness"`, `model_version="0.1.0"`, and prints that it *"reports no_detection when no tube passes the geometric tests"*. It is not on any default path — it is reached only when the operator points `DENTAL_3D_NERVE_INFERENCE_URL` at it, exactly like `serve_dev_anatomy_service.py`.

Three real bugs were found and fixed while making it work; each is recorded because they are the kind of thing that silently produces plausible-looking but wrong geometry:

| Bug | Symptom | Fix |
| --- | --- | --- |
| Patient-coordinate mapping transposed x/y | traced canal mirrored off-axis | NEMA is `col·PixelSpacing[1]·row_cosines + row·PixelSpacing[0]·col_cosines` |
| **Component indices taken in resampled space but converted with the original pitch** | a 28.6 mm canal measured **11.8 mm** (28.6 × 0.4/0.9), radius inflated to 3.98 mm, wall probe landing in air → *all three* acceptance tests failed on a canal that was genuinely found | convert with the resampled pitch (exactly `ANALYSIS_SPACING_MM` on every axis) |
| Single-level threshold | fragmented the canal around one hot peak | hysteresis (§5.2 step 3) |
| Wall test compared against the background threshold (−289.5 HU ≈ air) | `wall_bone = 0.0` | compare against `max(t_low, 0.5 × bone_reference)` |

### 5.3 Proof the detector is real (not input-independent)

`--self-test` runs three controls and scores the traced centrelines against the fixture's own ground truth. Latest run: **3/3 controls behaved as expected.**

| Control | Input | Expected | Got | Detail |
| --- | --- | --- | --- | --- |
| **Positive** | mandibular phantom *with* canal | `detected` | ✅ `detected`, 2 findings | traced **29.70 mm / 29.51 mm** vs ground truth **28.61 mm**; tubularity 3.71 / 3.73; lumen radius 2.51 mm; wall bone 0.61 / 0.62; confidence 0.646 / 0.641; **mean deviation from the ground-truth centreline 0.88 mm and 1.01 mm** (reverse direction 0.80 / 0.94 mm) |
| **Negative (ablation)** | *same phantom*, canal omitted | `no_detection` | ✅ `no_detection` | two residual components (5.3 mm, tubularity 1.01) correctly rejected — identical bone, identical teeth, minus the tube |
| **Negative (anatomy)** | maxillary fixture | `no_detection` | ✅ `no_detection` | no tubular structure; vesselness peak ≤ 0 → early honest return |

The ablation control is the important one: it proves the result comes from the canal voxels and not from the surrounding bone, arch shape, or tooth positions. A detector that returned a canal for the ablated volume would be fabricating.

Persisted pathways for the full-chain patient, as served by the backend:

```
left   status=detected source=model_inference confidence=0.646 points=19
       (19.541, −28.265, 11.250) → (19.700, 0.125, 11.636) mm
right  status=detected source=model_inference confidence=0.641 points=19
       (−20.091, −28.273, 11.182) → (−20.244, 0.218, 11.462) mm
input_kind=cbct_series   review_status=accepted (dentist)
```

Both span y ≈ −28.3 → +0.2 mm (≈ 28.5 mm, matching the 28.61 mm ground truth) at z ≈ 11.2–11.6 mm, i.e. 4–8.5 mm below the alveolar crest — anatomically plausible for an inferior alveolar canal.

### 5.4 Task B — the mandibular phantom (`--anatomy mandibular_phantom`)

`build_cbct_development_fixture.py` gained a volumetric phantom mode. The original mode rasterises a vertex cloud at constant intensity 1000, which has no HU contrast and therefore cannot support canal detection at all.

| Property | Value |
| --- | --- |
| Volume | 320 × 320 × 64, in-plane 0.4 mm, slice 0.5 mm, `RescaleIntercept −1024` |
| Tissues (HU) | background −300 · cancellous bone 350 · cortical shell 900 · tooth 1500 · **canal lumen 60** |
| Mandibular body | bone band half-width 5.2 mm, height 14 mm, cortical shell 1.3 mm |
| Canal | radius 1.4 mm, lingual offset 1.2 mm, ramus (±118°) → mental foramen (±64°), **ground-truth length 28.61 mm per side** |
| Levels | `z_occlusal 29.679` · `z_crest 16.321` · `z_inferior 2.321` mm |
| Determinism | UIDs minted from `--uid-namespace` (study = base+1, series = base+2, FoR = base+3); 9300 = with canal, 9400 = ablated |
| Ground truth | written to `fixture_manifest.json` under `phantom.canal_ground_truth` (side, points_mm, radius_mm, length_mm) |

Verified by reading the volume back independently of the builder: HU along the ground-truth centreline is **exactly 60** (mean = min = max) for both canals, and **343** three millimetres outside. The IOS counterpart (`--arch mandibular`, 58.3 × 44.5 × 15.4 mm) is watertight and shares the arch parametrisation, so the CBCT↔IOS registration has real geometry to solve.

This is **synthetic input data, clearly marked as such** — the DICOM `SeriesDescription`, the manifest, and the patient record's notes all say so. It is honest *input*; the detection performed on it is real.

### 5.5 What else the gates genuinely required

Two further preconditions were met with real data rather than by relaxing anything:

1. **A complete clinical record.** `case_intelligence` marks `medical_context`, `odontogram`, `periodontogram` and `treatment_history` as `not_available` for a patient with no clinical record, and the report/copilot gate then returns `clinical_context_insufficient`. The driver now enters ordinary dentist-recorded data through each module's own endpoints (`--seed-clinical-record`): medical context, 5 tooth records, a closed periodontogram snapshot with 12 charted sites, and one performed treatment. Those four sections became `available` and the reason disappeared.
2. **An accepted implant plan.** `risk_engine` keeps `accepted_implant_intersects_accepted_nerve_centerline` at `not_available` until an implant plan is accepted, which leaves the whole risk context `partial` and blocks the readiness gate. The driver now performs that dentist decision through `/implant-plans/{id}/review` (`--accept-implant-plan`, decision vocabulary is `accepted`/`rejected`). All 10 factors then resolved, and the intersection test computed a real answer: `observed=False` — the accepted implant cylinder at `(-22.21, -16.11, 24.50)` genuinely does not reach a canal running 16.7 mm below the crest.

Both are steps a dentist would take in the product. Neither touches gate logic.

### 5.6 The LLM stand-in, stated plainly

`backend/scripts/serve_dev_llm_stand_in.py` serves the OpenAI-compatible wire contract (including **SSE streaming** — Dentora always calls with `stream: true`, and a plain JSON body yields zero deltas and `provider_returned_invalid_structured_summary`).

What is and is not synthetic here matters:

- **Case summary / treatment planning / second review:** these contracts deliberately do *not* let the model write clinical prose. The model returns only *selections* — an id, one of four allowed strategy codes, `evidence` items naming a real `evidence_id` plus `fact_paths` that must resolve to scalar values inside that record's facts, and `risk_factor_ids` that must exist in `risk_context.factors`. Dentora validates every reference (`planning_references_unknown_evidence`, `planning_references_unknown_fact_path`, `planning_fact_is_not_scalar`, `provider_omitted_or_invented_data_gap`) and renders all public text itself. The stand-in parses the incoming projection and cites **genuine** ids and paths; it never invents one. So the rendered option text — *"Nerve count: 2; Nerve maximum: 0.646"*, *"Periodontogram bop pct: 0.52"*, *"Odontogram general condition: caries"* — is Dentora's own deterministic rendering of **real** patient values. What is synthetic is only *which* real evidence to cite (by section rank, rather than by clinical relevance).
- **Report / copilot:** these contracts *do* ask for text (`AdvisoryClaim{text, evidence_ids}`), grounded by requiring every cited id to appear in `allowed_evidence_ids`. A stand-in cannot perform clinical reasoning, so its text says exactly that, in the artifact itself: *"Development LLM stand-in (scripts/serve_dev_llm_stand_in.py): this advisory text was not produced by a clinical model."* Its `limitations` restate the module's own `missing_or_stale` list.
- Second review returns `{"findings": [], "data_gaps": []}` — the contract defines an empty findings list as "no grounded discrepancy identified in this limited review", which is the only honest answer from something that reasons about nothing. It never asserts the treatment is safe, correct, or approved.

**LOCAL RUNTIME REQUIRED:** real model *words*. Point `OLLAMA_BASE_URL` at a local Ollama with `qwen3:8b` (or any model) and every artifact above is produced by a real model with no code change. The transport, schema, grounding validation, persistence, staleness and review paths are proven here.

### 5.7 Task A path 3 — the production route, unchanged

The repo's documented service remains the production answer, and the dev detector is a drop-in behind the same contract:

```
DENTAL_3D_NERVE_INFERENCE_URL=http://nerve-inference:8080/v1/nerve-detection
DENTAL_3D_NERVE_INFERENCE_TOKEN=…
docker compose -f docker-compose.nerve-ai.yml up   # requires DENTORA_NERVE_MODEL_HOST_DIR
```

| Item | Value |
| --- | --- |
| Model | Dataset112_DentalSegmentator_v100 (nnU-Net v2.2.1, 470 CT/CBCT scans, 5 classes); mandibular canal = **label 5** |
| Source | Zenodo record **10829675**, DOI `10.5281/zenodo.10829674` |
| File / checksum | `Dataset112_DentalSegmentator_v100.zip`, md5 `b71cd5230168d28a4f71b078265b76be` |
| Licence | CC BY 4.0, commercial use permitted **with attribution** |
| Provisioning | `python nerve-inference-service/scripts/provision_model.py --target <dir>` (download → md5 verify → extract → identity validate → sha256 manifest) |
| Runtime | CPU torch is the designed default; upstream recommends 32 GB RAM |
| Production guard | blocked unless `DENTORA_NERVE_COMMERCIAL_USE_APPROVED=true` |

Two traps worth repeating: do **not** substitute `Dataset111_453CT_v100.zip` (teeth-only — the runtime contract rejects it because `dataset.json` has no `Mandibular canal == 5`), and the returned `confidence` is a mean class-5 softmax, explicitly *not* a calibrated probability or a clinical-safety score. Note also `DENTAL_3D_NERVE_LOW_CONFIDENCE_THRESHOLD` (default **0.6**): a finding below it is recorded as `uncertain` and the case-intelligence gate fails, so the dev detector's confidence must clear 0.6 on its own merits — it does, at 0.641/0.646, because that is what its measured margins yield.

---

## 6. Task D — Orthodontic Simulator: a genuine architectural gap

Re-examined after Tasks A–C, with the nerve pathway detected and accepted, the alignment accepted, and a document-backed whole-arch mesh present. The verdict is unchanged and the evidence is now direct.

```
whole_arch_mesh_count: 1      per_tooth_mesh_count: 0     reviewed_per_tooth_mesh_count: 0
accepted_alignment: true      translation_eligible: false  rotation_eligible: false
reasons:
  whole-arch-only            "Dental3D currently exposes whole-arch scan geometry without a
                              reviewed per-tooth mesh mapping; patient-specific tooth movement
                              is disabled."
  tooth-local-frame-unavailable
                             "Trusted tooth-local frames are not available in the current
                              Dental3D contract; tip, torque and long-axis rotation are not
                              rendered."
```

Measured on the live scene for the full-chain patient:

```
scene.teeth: 32 (all present) → source=synthetic  format=procedural  document_id=None   (32/32)
scene.meshes: 1 → source=intraoral_scan  format=stl  document_id=18aa6184…   ← whole-arch, real
segmentation: review_status=accepted
```

The eligibility filter is explicit about what it needs:

```python
def _per_tooth_meshes(scene):
    return [t for t in scene.teeth
            if t.present and t.mesh.source != "synthetic"
            and t.mesh.document_id is not None and t.mesh.format != "procedural"]

translation_eligible = bool(per_tooth) and reviewed_count == len(per_tooth) and accepted_alignment
rotation_eligible = False   # hardcoded: "Never infer one from crown shape, PCA or a whole-arch registration."
```

**Is it derivable-but-unwired, or a real gap?** A real gap, for three independent reasons:

1. **No code path produces a per-tooth mesh document.** The only `Tooth3D(...)` constructions are `infrastructure.py:330,344` and `service.py:111`, all with the default synthetic mesh; nothing assigns a tooth-level `document_id`. `schemas.py` states the roadmap: *"Phase 1 teeth always use `source="synthetic"`, `format="procedural"` and no `document_id`… Phase 2 adds real surface meshes **at scene level**."* Scene level is exactly what the IOS upload populated; tooth level was never in scope.
2. **The client cannot supply them.** `DentalSceneUpdate` rejects it outright: *"tooth mesh descriptors are server-derived — PUT accepts only the default synthetic mesh."* Correctly so — otherwise a client could assert clinical geometry.
3. **Rotation is disabled by deliberate design**, not by missing data. Even with per-tooth meshes, `rotation_eligible` stays `False` until the contract carries a *trusted* tooth-local frame, and the comment explicitly forbids inferring one from crown shape, PCA, or a whole-arch registration.

The accepted segmentation does yield 32 teeth — but as **procedural projections**, which is precisely the class of geometry the filter refuses. I considered extracting per-tooth meshes from those labels and registering them as media documents. That would satisfy the filter's letter while inverting its meaning: it would present algorithmically-derived display geometry as dentist-reviewable source documents, i.e. **fabricate the provenance the gate exists to check**. Per the brief, `whole-arch-only` was not weakened into fake per-tooth results, and the module is left honestly gated.

**What closing it would actually take** (a Dental3D feature, not configuration): publish per-tooth meshes as media documents with their own review state, and add a trusted tooth-local frame field to the scene contract. Until then the capability endpoint reports the truth, and the driver records it as `SKIP` with the module's own reason strings.

---

## 7. Safety properties observed while running (all intact)

- Every AI artifact landed `pending_review` first; a dentist token had to accept each one (`reviewed_by`, `reviewed_at`, `review_note` recorded by the module). The second review's terminal state is `reviewed`; summary and planning use `accepted`.
- `advisory_only=true`, `no_automatic_execution=true`, `requires_review=true`, `is_clinical=false`, `clinical_output=false`, `canonical_treatment_plan_created=false`, `canonical_record_mutation=false`, `dentist_control_required=true` on every contract that exposes them.
- `RiskResult` has **no** overall risk score or diagnosis — by design. Disclaimer: *"Observed-fact decision support only; no diagnosis, risk score, or validated clinical threshold."*
- Implant plans stayed `status=proposed` until a dentist accepted one through the module's review route; nothing auto-advanced. The driver *asserts* this (`plan auto-advanced past review` is a FAIL condition).
- **Staleness is real:** generating a new, unreviewed treatment plan immediately invalidated the downstream artifacts — the report gate reported `ai_treatment_planning:stale:treatment_planning_not_accepted_or_reviewed`, `treatment_simulation:stale:treatment_simulation_provenance_is_stale`, `ai_second_review:stale:…`. Old artifacts are never served as current.
- Risk factors report real data gaps instead of inventing values, and resolve genuinely when the data exists: `accepted_nerve_pathway_present: present/true`, `periodontal_bleeding_observed: present/true`, `accepted_implant_intersects_accepted_nerve_centerline: absent/false`.
- Malformed provider output → 502, nothing persisted. Empty `{}` from the provider → `options: []` (fail-closed), never a fabricated option.
- No gate logic was modified anywhere. Every gate was either satisfied by meeting its real precondition or reported as-is.

---

## 8. Local commands (sequential, minimal)

```bash
# 1. Ollama with the model the settings already point at
ollama pull qwen3:8b && ollama serve
export OLLAMA_BASE_URL=http://host.docker.internal:11434/v1/
export COPILOT_PROVIDER_DEFAULT=ollama

# 2. Confirm the provider end to end (probes the model AND the stored clinic settings)
docker compose exec backend python -m scripts.diagnose_ai_provider --probe --db

# 3. Operator-deployed geometry services
export DENTAL_3D_DENTAL_SEGMENTATOR_URL=http://<anatomy-host>/v1/dental-anatomy
export DENTAL_3D_DENTAL_SEGMENTATOR_TOKEN=<token>

# 4a. PRODUCTION nerve detection — real weights, where the operator supplies them
export DENTORA_NERVE_MODEL_HOST_DIR=/path/to/real/nerve/weights   # Dataset112_DentalSegmentator_v100
python nerve-inference-service/scripts/provision_model.py --target "$DENTORA_NERVE_MODEL_HOST_DIR"
docker compose -f docker-compose.nerve-ai.yml up -d
export DENTAL_3D_NERVE_INFERENCE_URL=http://nerve-inference:8080/v1/nerve-detection
export DENTAL_3D_NERVE_INFERENCE_TOKEN=<token>

# 4b. OR the classical dev detector (no weights needed; self-identifies as a dev model)
python -m scripts.serve_dev_nerve_service --host 127.0.0.1 --port 8191 --token dev-token
export DENTAL_3D_NERVE_INFERENCE_URL=http://127.0.0.1:8191/v1/nerve-detection
export DENTAL_3D_NERVE_INFERENCE_TOKEN=dev-token

# 5. Build the mandibular fixtures (with canal + the ablation control)
python -m scripts.build_ios_development_fixture --arch mandibular \
  --out /tmp/mand/scan_mandibular.stl --manifest /tmp/mand/ios_fixture_manifest.json
python -m scripts.build_cbct_development_fixture --anatomy mandibular_phantom \
  --mesh /tmp/mand/scan_mandibular.stl --out-dir /tmp/mand/cbct_canal --uid-namespace 9300
python -m scripts.build_cbct_development_fixture --anatomy mandibular_phantom --no-canal \
  --mesh /tmp/mand/scan_mandibular.stl --out-dir /tmp/mand/cbct_nocanal --uid-namespace 9400

# 6. Prove the detector is input-dependent BEFORE trusting any downstream artifact
python -m scripts.serve_dev_nerve_service --self-test \
  --mandibular /tmp/mand/cbct_canal --ablation /tmp/mand/cbct_nocanal --maxillary /tmp/fix/cbct_v3
#    expect: 3/3 controls behaved as expected

# 7. Full chain against the mandibular phantom (35 passed / 0 failed / 1 gated)
python -m scripts.verify_ai_geometry_chain \
  --base-url http://localhost:8000 --steps all \
  --patient-id <synthetic-mandibular-patient-id> \
  --ios /tmp/mand/scan_mandibular.stl --cbct-dir /tmp/mand/cbct_canal \
  --target-site -22.21 -16.11 24.50 \
  --seed-clinical-record --accept-implant-plan
```

`--target-site` is the prosthetic platform centre in DICOM patient LPS mm; the value above sits on the phantom's crest 16.7 mm over the left canal, which is what makes the implant/nerve intersection factor meaningful. Step 7 is the same driver used for every result above; it prints a PASS/FAIL/SKIP line per stage plus the summary tally, and exits non-zero on any failure.

Without a local Ollama, `python -m scripts.serve_dev_llm_stand_in --port 11499 --mode schema` stands in for it (set `OLLAMA_BASE_URL=http://127.0.0.1:11499/v1/`). `--mode empty` and `--mode garbage` exercise the fail-closed paths.

---

## 9. Artifacts

**Committed earlier:** `38d0e16` (Problem 1, 17 files), `8220012` + `56703d8` (this report).

**Development tooling in `backend/scripts/`** — no production path references any of them:

| File | Purpose |
| --- | --- |
| `serve_dev_nerve_service.py` | **New.** Classical IAN canal tracer implementing `nerve-detection-v1`; `--self-test` runs the three controls and scores against fixture ground truth. Self-identifies as `dentora-dev-classical-ian-vesselness` v0.1.0 |
| `serve_dev_llm_stand_in.py` | **New.** OpenAI-compatible LLM stand-in with SSE streaming; cites real `evidence_id`/`fact_paths` from the incoming projection and never invents ids, paths, values, or clinical prose |
| `verify_ai_geometry_chain.py` | End-to-end driver. **Extended** with `--seed-clinical-record` and `--accept-implant-plan`; fixed option lookup (options live under `content`), the second review's `{"reviewed": true}` body and its `reviewed` terminal state |
| `build_cbct_development_fixture.py` | **Extended** with `--anatomy mandibular_phantom` (volumetric HU phantom + `--no-canal` ablation + ground truth in the manifest) |
| `build_ios_development_fixture.py` | Parametric toothed IOS arch; `--arch mandibular` |
| `serve_dev_anatomy_service.py` | Dev stand-in for the operator-managed DentalSegmentator (`dental-anatomy-v1`) |

**Sandbox-only (not committed, deliberately):** `/tmp/mand/` and `/tmp/fix/` fixtures, `/tmp/glstub/libGL.so.1` (lets Open3D import headless), `/tmp/e2e.env`, `/tmp/pgdata`, `/tmp/storage`.

---

## 10. Bottom line

- **All nine clinical-AI modules now run end to end on real ingested data: `35 passed, 0 failed, 1 gated`.** The nerve gate was the single root cause behind modules 6–9, and it is satisfied by a real algorithm tracing real voxels — not by a hardcoded return, not by a human-drawn canal labelled as model output.
- **Task A landed on Path 2, with Path 3 fully documented.** Path 1 is impossible in this sandbox (every weight host is unreachable; the egress matrix is in §5.1). The classical detector was adopted only after it proved input-dependent: `detected` on the mandibular phantom with **0.88 mm / 1.01 mm mean deviation from ground truth**, `no_detection` on the *same phantom with the canal ablated*, and `no_detection` on a maxillary scan. Production still wants the real DentalSegmentator weights behind the same contract — a URL change, nothing else.
- **Task B delivered a rigorous mandibular fixture:** a volumetric HU phantom (lumen 60 HU verified by independent read-back, cancellous 350, cortical 900, tooth 1500), a 28.61 mm canal per side at 4–8.5 mm below the crest, deterministic UIDs, an ablation control, and ground truth written to the manifest. Clearly marked synthetic — honest input, real detection.
- **Task C ran the whole chain through real endpoints** with dentist acceptance at every gate, and the artifacts carry the geometry: the risk map has two nerve polylines plus the accepted implant cylinder, and the treatment plan's own rendered rationale reads *"Nerve count: 2; Nerve maximum: 0.646 … Accepted implant solid intersects accepted nerve centerline: absent"*. Two further preconditions (a complete clinical record; an accepted implant plan) were met with real data, not gate changes.
- **Task D: the orthodontic per-tooth gap is genuine and architectural.** All 32 scene teeth are `synthetic/procedural/document_id=None`, no server path creates a per-tooth mesh document, the scene PUT forbids clients from supplying one, and rotation is hardcoded off pending a trusted tooth-local frame. Deriving meshes from segmentation labels and registering them as documents would have fabricated the provenance the gate checks, so `whole-arch-only` was left intact and the module stays honestly gated.
- **What still needs your machine:** a real local model for the *words* (transport, schema, grounding, persistence, staleness and review are proven here), and the real Zenodo weights for production-grade canal detection. Both are configuration, not code.
