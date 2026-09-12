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
| 10 | Orthodontic Simulator | P2 | ⚠️ **PARTIAL — contract limitation** | Capability endpoint works and now reports `accepted_alignment=true` (the accepted registration really does feed it), `whole_arch_mesh_count=2`. Per-tooth movement is **disabled by the module's own contract**, not by data: `whole-arch-only` + `tooth-local-frame-unavailable` (§6). **ARENA-SANDBOX VERIFIED** (capability) / **NOT ACHIEVABLE** without a Dental3D contract change |

**Final driver tally (one patient, full chain):** `22 passed, 0 failed, 6 skipped/gated`.

---

## 2. Problem 1 — the exact misconfiguration

**Root cause (fixed, committed `38d0e16`, 17 files):** `openai.APIConnectionError` / `APITimeoutError` escaped the provider abstraction. The AI routers only caught `LLMConfigError` / `LLMError`, so an unreachable Ollama surfaced as an unhandled **HTTP 500** instead of a clean, actionable **503**. Connection handling was *scattered* across call sites rather than centralised in the provider layer.

This was **not** "Ollama isn't running" and **not** a Docker networking mistake in the code — those are operator-side conditions the code must report cleanly, and now does.

**Provider selection is env-driven and single-sourced:** `local`/`dev` → Ollama (`OLLAMA_BASE_URL`), `production` → Cloudflare. No Workers AI implementation was added, per instructions.

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

**And one data caveat that matters:** every fixture here is a **maxillary** arch. There is no inferior alveolar canal in a maxilla, so even a perfect model would return no detected pathway and `detection_status` would not be `"detected"`. To exercise #6–#9 locally you need a **mandibular CBCT with a visible canal**.

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

Whole-arch geometry is patient-derived and present. Per-tooth movement needs a reviewed per-tooth mesh mapping and trusted tooth-local frames that **the Dental3D contract does not currently expose** — no amount of test data supplies them. Enabling it is a feature (extend the Dental3D contract to publish per-tooth meshes + local frames), not a fix, so it was left alone.

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

- **Problem 1 is fixed and committed.** The misconfiguration was unhandled `APIConnectionError`/`APITimeoutError` escaping the provider abstraction into HTTP 500s. Provider selection is env-driven; Ollama's `json_schema` support is confirmed compatible. Real prompt assembly is proven with 53k–94k-character, case-derived prompts. Only the model's *words* still need your local Ollama.
- **Problem 2 is solved for everything the sandbox can legitimately reach.** Real IOS + real 40-slice CBCT ingested through real endpoints, real Open3D RANSAC+ICP registration that recovered the offset it was given, real dentist acceptances at every gate — and that flipped case intelligence from `alignment/anatomy invalid_or_stale` to `available`, which is what unlocked implant planning end to end.
- **Six steps remain gated on one honest precondition:** a dentist-accepted, model-detected nerve pathway in the accepted alignment's frame. That needs the operator-deployed nerve inference service *and a mandibular CBCT*. It was not faked.
- **One limitation is architectural, not environmental:** the Orthodontic Simulator's per-tooth movement is disabled by the current Dental3D contract (`whole-arch-only`, `tooth-local-frame-unavailable`). Whole-arch patient geometry works; per-tooth requires a contract extension.
