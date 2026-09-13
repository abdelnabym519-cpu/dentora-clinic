# Real Models, Verified Licensing, and Demo Data Visible in the UI

Branch: `arena/01a091f7-dentora-clinic` · Environment: Arena sandbox (`E2B_SANDBOX_ID=ienfzsyxcv0isbnwircri`) · Date: 2026-09-13

## Headline

| Goal | Status | Why |
| --- | --- | --- |
| **A. Real DentalSegmentator nerve weights** | **BLOCKED — not obtainable here** | Zenodo is TLS-blocked by the sandbox egress allowlist, and there is no `docker` binary. Licensing was verified **affirmative** first, so this is purely a network/tooling blocker. |
| **A2. License permits commercial dental-product local inference** | **VERIFIED — YES** | Weights are **CC BY 4.0** (attribution only, no non-commercial clause). Code is **Apache-2.0**. Legal text read directly; details below. |
| **B. Real Ollama LLM output** | **BLOCKED — not obtainable here** | No `ollama` binary, `registry.ollama.ai` TLS-blocked, `localhost:11434` connection refused. |
| **C. Demo data visible in the running UI** | **DELIVERED** | Found and fixed a real wiring bug that was hiding **all 8 AI/3D cards** from the UI. Two `(SYNTHETIC)` demo patients now carry a full real artifact chain. |

Nothing in this report claims local-runtime success. Verification levels are tagged per item in §6.

---

## 1. Task A — real nerve model

### 1.1 License verdict: AFFIRMATIVE (commercial use permitted)

This was checked **before** any attempt to wire weights in, as required.

**Weights — CC BY 4.0.** Zenodo record `10829675`, file `Dataset112_DentalSegmentator_v100.zip`, MD5 `b71cd5230168d28a4f71b078265b76be` — these identifiers match `nerve-inference-service/README.md` exactly. The record's license was independently corroborated by a third-party audit (`ainem-m/TotalSegmentatorWrapperForWin`, `docs/41_OPEN_SOURCE_LICENSE_AUDIT.md`, which queried the Zenodo API on 2026-07-28 and records license id `cc-by-4.0`, creator Dot Gauthier, ORCID 0000-0003-2014-2623).

The **CC BY 4.0 legal text was read directly** (fetched from a mirror, since `creativecommons.org` is also blocked). Verbatim:

- §2(a) grant: *"a worldwide, royalty-free, non-sublicensable, non-exclusive, irrevocable license to exercise the Licensed Rights in the Licensed Material to: (1) reproduce and Share the Licensed Material, in whole or in part; and (2) produce, reproduce, and Share Adapted Material."*
- §3 conditions: attribution — identify the creator, provide a copyright notice, provide a license notice, provide a warranty-disclaimer notice, and indicate if changes were made.
- The string `noncommercial` appears **0 times** in the license text.

**Conclusion:** local inference inside a commercial dental product is permitted, subject to attribution. No non-commercial / research-only restriction applies.

**Code — Apache-2.0**, read directly from the upstream repositories: `gaudot/SlicerDentalSegmentator` (`LICENSE.txt`, "Copyright (c) 2024, Gauthier DOT") and `MIC-DKFZ/nnUNet` (`LICENSE`). Apache-2.0 is permissive for commercial use.

**Attribution to ship with the weights** (satisfies CC BY 4.0 §3):
Dot G, et al. *Journal of Dentistry* (2024), doi:10.1016/j.jdent.2024.105130 · Zenodo doi:10.5281/zenodo.10829675 · Licensed CC BY 4.0.

Note: `ahzs645/CBCTer` (MIT) was also inspected; it has no `LICENSING.md`, so the citation in Dentora's README does not resolve there. It was **not** used, and no unlicensed substitute was silently adopted.

### 1.2 The download itself: blocked, with exact evidence

```
$ python nerve-inference-service/scripts/provision_model.py --target /tmp/nerve_weights
PROVISION FAILED: cannot reach Zenodo record 10829675
                  (<urlopen error TLS/SSL connection has been closed (EOF)>)
```

Corroborating environment facts: `zenodo.org`, `huggingface.co`, `registry.ollama.ai`, `creativecommons.org`, `download.pytorch.org`, `storage.googleapis.com` and `*.githubusercontent.com` all fail TLS with `SSL_ERROR_SYSCALL` while DNS resolves — the signature of an egress allowlist. Reachable: `pypi.org`, `files.pythonhosted.org`, `github.com`, `api.github.com`, `codeload.github.com`, `registry.npmjs.org`. There is **no `docker` binary**, so `docker compose -f docker-compose.nerve-ai.yml up -d` cannot run here either.

`provision_model.py` already has the right escape hatch: `--zip <path>` performs an MD5-gated manual install, and it refuses to change model identity. **Steps A3–A5 therefore require your machine, not a code change.**

### 1.3 What is actually running in its place

The classical vesselness detector, which **self-identifies honestly** in every artifact:

```
provenance.model_id      = dentora-dev-classical-ian-vesselness
provenance.model_version = 0.1.0
provenance.adapter       = dentora-cbct-http-v1
is_clinical              = False
requires_review          = True
```

It is **not** `serve_dev_nerve_service`, and it is not presented as DentalSegmentator. Its input-dependence is proven by three controls, re-run this session against the exact fixture now loaded into the demo patient:

```
mandibular + canal  -> detected, 2 pathways, mean deviation 0.91 mm / 1.16 mm
canal ablated       -> no_detection, 0 findings
maxillary (no canal)-> no_detection, 0 findings
3/3 controls behaved as expected
```

When real weights are provisioned, `model_id` must change to the DentalSegmentator identity — that is the acceptance test for A4.

---

## 2. Task B — real LLM output

### 2.1 Blocker, with exact evidence

```
$ python -m scripts.diagnose_ai_provider --probe --db     # OLLAMA_BASE_URL=http://localhost:11434/v1/
x TCP connect REFUSED ([Errno 111])
VERDICT ollama/qwen3:8b is NOT usable
```

No `ollama` binary exists in the sandbox and `registry.ollama.ai` is TLS-blocked, so `qwen3:8b` cannot be pulled. The configured provider/model (`ollama` / `qwen3:8b`) is therefore unreachable, and the labelled development stand-in remains in the path.

### 2.2 Actual generated text (verbatim) — proof of what is and is not real

This is the real response body from `POST /api/v1/ai_clinical_report/generate` for the demo patient, not a status code:

> "Focus case_review — Development LLM stand-in (scripts/serve_dev_llm_stand_in.py): this advisory text was not produced by a clinical model. It cites the listed evidence ids from the accepted Dentora evidence chain and performs no clinical reasoning."
>
> "Additional accepted evidence was available to this advisory step; the stand-in cites it without interpretation. Run a real local model to obtain clinically reasoned advisory text."

Accompanying metadata from the same response:

```
limitations: ["Advisory text generated by a labelled development stand-in, not a clinical model."]
advisory_only: True            dentist_review_required: True
autonomous_diagnosis: False    autonomous_treatment_decision: False
canonical_record_mutation: False
provenance.provider: ollama    provenance.model: qwen3:8b
```

`POST /api/v1/clinical_copilot/advise` returns the same self-identifying text with the same flags.

**Honest reading:** the *plumbing* is real (provider resolution, evidence binding, digests, review gates), the *evidence* is real (202 refs), but the *language* is templated by the stand-in and says so. That is the correct behaviour given the blocker, and it is what your constraint required — a dev-only service must self-identify.

The persisted, dentist-accepted case summary shows the difference clearly. Its claims are built from real record data but labelled as stub-generated:

```
CLAIM-STUB-01  "Nerve — count: 2; maximum: 0.65; mean: 0.645."                        evidence: E008
CLAIM-STUB-04  "Periodontogram — closed at: 2026-09-12T22:59:01Z; bleeding on probing: no."  evidence: E203
CLAIM-STUB-05  "Odontogram — general condition: healthy; is displaced: no; is rotated: no."  evidence: E088
```

The nerve numbers are the detector's real output; the periodontal facts are the demo patient's real seeded observations.

---

## 3. Task C — the bug that was hiding the entire AI UI

### 3.1 Symptom

The Nuxt app has only 9 pages of its own (`login`, `setup`, `activate`, `index`, `settings/*`, `trial-expired`). Everything else — including every patient page — is contributed by **Nuxt layers** under `frontend/module_layers/`, registered through `frontend/modules.json`, which the backend regenerates at startup.

Two defects stacked on top of each other meant the AI features were invisible:

**Defect 1 — `modules.json` was stale (20 layers instead of 29).** The backend's layer sync writes to `settings.DENTORA_FRONTEND_ROOT`, which defaults to `/host_frontend` (a Docker mount). Outside Docker that path does not exist, so every startup logged:

```
ERROR app.core.plugins.processor: Frontend layer sync failed (non-fatal)
PermissionError: [Errno 13] Permission denied: '/host_frontend'
```

The sync is non-fatal by design, so the app booted happily with a stale file that omitted **all 8 AI/3D layers** — `case_intelligence`, `ai_case_summary`, `ai_clinical_report`, `ai_treatment_planning`, `treatment_simulation`, `ai_second_review`, `clinical_copilot`, `dental_3d`. Fix: set `DENTORA_FRONTEND_ROOT` to the real frontend root. On restart the backend logged `Wrote /home/user/dentora-clinic/frontend/modules.json with 29 layer(s)`. `modules.json` was backed up to `/tmp/modules.json.bak` before regeneration and was **not** hand-edited — it was rewritten by the backend's own atomic writer.

**Defect 2 — layer paths are container-absolute, so Nuxt dropped all 29 layers.** Module manifests declare `layer_path` as `/module_layers/<module>/frontend`, correct inside the frontend image. `nuxt.config.ts` passed those strings straight to `extends`, so Nuxt resolved them against the filesystem root and silently skipped every layer:

```
WARN  Cannot extend config from /module_layers/dental_3d/frontend in /home/user/dentora-clinic/frontend
WARN  Cannot extend config from /module_layers/ai_case_summary/frontend ...
```

Fix (smallest correct change, `frontend/nuxt.config.ts`): resolve a declared layer path under the frontend root **only when the absolute path does not exist on disk**. Container behaviour is byte-for-byte unchanged, because an existing absolute path is returned untouched.

### 3.2 Proof the fix took effect

From the generated build artifacts:

```
distinct layers resolved by Nuxt: 29   (was 20 declared / 0 loadable)
  includes ai_case_summary, ai_clinical_report, ai_second_review,
           ai_treatment_planning, case_intelligence, clinical_copilot,
           dental_3d, treatment_simulation
component registry: AICaseSummaryCard REGISTERED · AIClinicalReportCard REGISTERED
  AISecondReviewCard REGISTERED · ClinicalCopilotCard REGISTERED
  Dental3DViewer REGISTERED · RiskEngineCard REGISTERED
```

And through the running UI, server-side rendered with a real session cookie:

```
GET /patients/e2eebc99-9c0b-4ef8-bb6d-6bb9bd380a62  -> HTTP 200, 87,456 bytes
SSR HTML contains: "Layla", "Adel", "SYNTHETIC" (x3)
```

---

## 4. Demo data — what was seeded, and how

**Sourcing decision (license-first).** No public dental imaging dataset with an explicit commercial-demo grant could be verified from this sandbox: the usual hosts (Zenodo, Hugging Face, Grand Challenge, Synapse, TCIA, Google Cloud Storage) are all TLS-blocked, so their license texts could not be read. Per the instruction not to substitute an unverified source, the demo data uses the repository's **own synthetic fixtures**, permanently labelled with the existing `(SYNTHETIC)` convention. No real or identifiable patient data is used anywhere.

The fixtures are anatomically plausible and self-documenting. `fixture_manifest.json` carries `"synthetic": true` plus canal ground truth, and each patient's CBCT is a deterministic DICOM series with its own namespace:

| Demo patient | Series namespace | Series UID |
| --- | --- | --- |
| Layla Adel (SYNTHETIC) | 9700 | `1.2.826.0.1.3680043.10.1337.9702` |
| Omar Sami (SYNTHETIC) | 9800 | `1.2.826.0.1.3680043.10.1337.9802` |

**Seeded through real endpoints only** — no DB-insert shortcut. Each patient went through media IOS upload → CBCT DICOM ingest → segmentation → dentist segmentation review → nerve detection → dentist nerve review → alignment → dentist alignment acceptance → prosthetic target → target review → risk engine → implant proposal → dentist implant acceptance → case intelligence → AI summary/planning/simulation/second review (each `pending_review`, then dentist-accepted) → report → copilot.

**Every acceptance was performed by the dentist token through the module's own review route.** No flag was written directly, and no gate was weakened.

### 4.1 Result per patient

| Patient | Chain result | Report + copilot | Notes |
| --- | --- | --- | --- |
| **Layla Adel (SYNTHETIC)** `e2ee…a62` | **31 passed / 0 failed / 1 gated** | **real output** | The primary demo. Only ortho per-tooth movement is gated (documented contract limitation). |
| **Omar Sami (SYNTHETIC)** `e1ee…a61` | 29 passed / 0 failed / 3 gated | gated | `risk_engine:unavailable:risk_context_partial` — his seeded record lacks a risk-relevant section, so the report gate correctly refuses. |
| Amina Hassan (SYNTHETIC) `e4ee…a64` | 29 passed / 0 failed / 3 gated | gated | Nerve detected and implant plan accepted, but `implant_planning` is `invalid_or_stale`: plans from my earlier experiments reference a superseded `alignment_id`. The staleness rule is correct and was not bypassed. |
| Sam Youssef (SYNTHETIC) `e3ee…a63` | 29 passed / 0 failed / 3 gated | gated | **My error, documented:** I first built his CBCT with the builder's default 12 slices instead of 64, shifting the phantom 13 mm down so the canal fell outside the volume. The detector returned `no_detection` rather than inventing a pathway, and the risk map reverted to `unavailable`. His record is now a genuine negative case, but it was caused by a bad fixture, not by design. |
| Nora Farouk (SYNTHETIC) `e0ee…a60` | — | — | Carries artifacts from earlier sessions; not part of this demo. |

**Use Layla Adel (SYNTHETIC) for the walkthrough.**

### 4.2 The real artifacts now on Layla

Nerve detection (`GET /api/v1/dental_3d/patients/{id}/nerve-detection`):

```
status: detected        pathways: 2        review_status: accepted
confidence_summary: count=2 min=0.64 max=0.65 mean=0.645
inference_duration_ms: 593
provenance.model_id: dentora-dev-classical-ian-vesselness
provenance.series_instance_uid: 1.2.826.0.1.3680043.10.1337.9702
is_clinical: False      requires_review: True
```

Scene (`GET .../scene`): 2 meshes from ingested scan documents, **0 procedural fallbacks**; 32 teeth; segmentation `completed`, 31 segmented / 1 uncertain / 0 missing, `review_status: accepted`, `non_clinical: True`.

Risk engine (`GET /api/v1/risk_engine/patients/{id}/latest`) — `result_version: 3`, `review_status: pending_review` (a real dentist should look), `advisory_only: True`, disclaimer *"Observed-fact decision support only; no diagnosis, risk score, or validated clinical threshold."*

10 factors, all from observed data:

| factor_id | state | observed |
| --- | --- | --- |
| `accepted_nerve_pathway_present` | present | True |
| `current_accepted_implant_plan_present` | present | True |
| `accepted_implant_intersects_accepted_nerve_centerline` | absent | False |
| `periodontal_bleeding_observed` | present | True |
| `periodontal_plaque_observed` | present | True |
| `periodontal_suppuration_observed` | present | True |
| `smoking_context_present` | present | True |
| `anticoagulant_context_present` | absent | False |
| `bruxism_context_present` | absent | False |
| `adverse_anesthesia_reaction_context_present` | absent | False |

The intersection factor is a real geometric computation: the accepted implant cylinder does **not** intersect the accepted nerve centerline, so it reports `False` rather than asserting a hazard.

3D risk map: `status: available`, `frame: {kind: dicom_patient, unit: mm, FoR …9703}`, **`synthetic_geometry: False`**, 3 regions —

- `nerve-pathway-1` polyline, from `(19.200, −27.884, 11.250)`
- `nerve-pathway-2` polyline, from `(−20.310, −27.915, 11.250)`
- `accepted-implant-1` cylinder, center `(−22.210, −16.110, 19.500)` — the seeded target site

202 evidence refs across 7 modules: `patient_timeline` 79, `media` 78, `odontogram` 34, `dental_3d` 8, `patients` 1, `patients_clinical` 1, `periodontogram` 1.

---

## 5. Click-through walkthrough (9 modules, real output)

Preview URLs: UI `https://3000-ienfzsyxcv0isbnwircri.e2b.app` · API `https://8100-ienfzsyxcv0isbnwircri.e2b.app`

1. Open the UI → you land on `/login`. Sign in as `dentist@demo.clinic` / `demo1234`.
2. `/patients` → find **Layla Adel (SYNTHETIC)**. The `(SYNTHETIC)` suffix is the permanent synthetic marker.
3. Open her record → `/patients/e2eebc99-9c0b-4ef8-bb6d-6bb9bd380a62`. The Summary tab renders the `patient.summary.cards` slot; the AI cards mount in this order:

| Order | Card | Module | What you should see |
| --- | --- | --- | --- |
| 50 | `Dental3DCard` | dental_3d | The 3D scene: 2 real ingested meshes, 32 teeth, accepted segmentation. Inside it, `Dental3DViewer` + `nerveView` draw the **2 detected nerve pathways** as polylines, and `RiskEngineCard` renders the **3 risk-map regions** (2 nerve polylines + 1 implant cylinder) in the DICOM patient frame. |
| 70 | `CaseIntelligenceCard` | case_intelligence | The evidence snapshot: section availability and the **202 evidence refs** with their source modules and validation states. |
| 71 | `AICaseSummaryCard` | ai_case_summary | Summary **version 3, `review_status: accepted`**, with claims such as *"Nerve — count: 2; maximum: 0.65; mean: 0.645"* and her real periodontal observations. Claim ids are prefixed `CLAIM-STUB-`, the honest stand-in label. |
| 72 | `AIClinicalReportCard` | ai_clinical_report | 6 sections (`case_intelligence`, `risk_engine`, `ai_treatment_planning`, `treatment_simulation`, `ai_second_review`, `cross_stage`) all `state: ready`, with `risk_engine` citing 202 refs. The generated text self-identifies as the development stand-in; `advisory_only: True`, `dentist_review_required: True`. |
| 73 | `AITreatmentPlanningCard` | ai_treatment_planning | The planning result, dentist-accepted, with options nested under `content`. |
| 74 | `TreatmentSimulationCard` | treatment_simulation | The deterministic simulation scene bound to the accepted plan option. |
| 75 | `AISecondReviewCard` | ai_second_review | The second-review result, dentist-accepted. |
| 76 | `ClinicalCopilotCard` | clinical_copilot | The advisory: 2 claims bound to evidence ids `E001–E008`, with the limitations banner *"Advisory text generated by a labelled development stand-in, not a clinical model."* |

4. The **9th module, `risk_engine`**, is the `RiskEngineCard` inside `Dental3DCard` (its slot permission is `risk_engine.read`). It shows the 10 factors above, including the honest `False` on implant/nerve intersection.
5. To see a gate refuse correctly, open **Omar Sami (SYNTHETIC)** `e1ee…a61` — his report and copilot cards stay gated on `risk_context_partial`.
6. Orthodontic movement is gated on every patient by contract: `whole-arch-only; tooth-local-frame-unavailable` (per-tooth meshes require tooth-level documents with real `document_id`, non-procedural, non-synthetic). This is a known gap, not a regression, and it was not weakened.

If a card is missing, the cause is almost always layer registration — check that `frontend/modules.json` lists 29 layers and that the dev server logs no `Cannot extend config` warnings.

---

## 6. Verification levels

| Item | Level |
| --- | --- |
| CC BY 4.0 / Apache-2.0 licensing verdict | **VERIFIED** (legal text read directly; record metadata independently corroborated) |
| Zenodo and Ollama unreachability | **ARENA/SANDBOX VERIFIED** (verbatim failures captured) |
| Classical detector 3/3 controls on the demo fixture | **ARENA/SANDBOX VERIFIED** |
| Layla's full chain, 31 passed / 0 failed | **ARENA/SANDBOX VERIFIED** |
| `modules.json` 29 layers, AI components registered | **ARENA/SANDBOX VERIFIED** (build artifacts) |
| Patient page SSR 200 with real data through the preview origin | **ARENA/SANDBOX VERIFIED** |
| **Client-rendered AI cards in a browser** | **NOT VERIFIED HERE** — no browser binary exists in the sandbox and `npx playwright install chromium` fails on download (egress-blocked). The cards are compiled in and their slot plugins are registered, but the slot system is client-only, so SSR cannot prove the paint. Confirm by opening the URL in §5. |
| Real DentalSegmentator weights in the container | **LOCAL RUNTIME REQUIRED** |
| Real `qwen3:8b` generated prose | **LOCAL RUNTIME REQUIRED** |

## 7. Commands for your machine (sequential, minimal)

```bash
# A3-A4: real weights, then the nerve service with them
python nerve-inference-service/scripts/provision_model.py \
  --target "$DENTORA_NERVE_MODEL_HOST_DIR"
docker compose -f docker-compose.nerve-ai.yml up -d

# A5: re-run the three controls against the real model and confirm model_id changed
#     away from dentora-dev-classical-ian-vesselness in the artifact provenance.

# B1-B2: real LLM
ollama pull qwen3:8b
cd backend && python -m scripts.diagnose_ai_provider --probe --db

# B3: full chain with both real components, on the demo patient
cd backend && python -m scripts.verify_ai_geometry_chain \
  --patient-id e2eebc99-9c0b-4ef8-bb6d-6bb9bd380a62 \
  --ios /tmp/mand/scan_mandibular.stl --cbct-dir /tmp/mand/demo_9700 \
  --target-site -22.21 -16.11 24.50 --accept-implant-plan --steps all

# C: the UI, with layer sync pointed at the real frontend root
DENTORA_FRONTEND_ROOT="$PWD/frontend" # export before starting the backend
cd frontend && npm run dev
```

Expected change once real models are in place: `provenance.model_id` names DentalSegmentator, and report/copilot `limitations` no longer carries the stand-in banner. Everything else — review states, `advisory_only`, `pending_review` on the risk result — should stay exactly as it is.

## 8. Files changed

- `frontend/nuxt.config.ts` — resolve container-absolute layer paths under the frontend root when absent on disk (+24/−2).
- `frontend/modules.json` — regenerated by the backend's own writer with the correct `DENTORA_FRONTEND_ROOT` (20 → 29 layers). Backup at `/tmp/modules.json.bak`.
- `docs/real-models-and-demo-data-report.md` — this report.

No gate logic, RBAC, review requirement, or safety control was modified. No cloud deployment. No autonomous diagnosis or treatment decision was introduced: every AI artifact remains `advisory_only: True` with `autonomous_diagnosis: False` and `autonomous_treatment_decision: False`.
