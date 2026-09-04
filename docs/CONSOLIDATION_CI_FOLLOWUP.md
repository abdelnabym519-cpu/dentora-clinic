# Consolidation follow-ups

## 1. REQUIRED: pgvector image in CI (must be applied by hand)

`.github/workflows/ci.yml`, `backend-test` job, `services.postgres.image`:

```diff
-        image: postgres:15-alpine
+        image: pgvector/pgvector:0.8.6-pg15-bookworm
```

### Why

`backend/app/core/retrieval/repository.py` issues:

```sql
SET LOCAL hnsw.iterative_scan = strict_order
```

`hnsw.iterative_scan` requires **pgvector >= 0.8.0**. The stock
`postgres:15-alpine` image ships no pgvector at all, so
`0010_vector_retrieval_foundation` cannot even run `CREATE EXTENSION vector`.

### Why it is not committed

The agent's GitHub App lacks the `workflows` permission; the remote rejects
any push touching `.github/workflows/**`:

```
refusing to allow a GitHub App to create or update workflow
`.github/workflows/ci.yml` without `workflows` permission
```

Reverting this single line was the only way to preserve the other 176 files.
**Apply it by hand before relying on CI.**

### Verification status: PASSING

pgvector **0.8.1** was built from source against the sandbox PostgreSQL 16.2
and all retrieval tests were then run:

```
tests/core/test_retrieval.py .......  6 passed
```

This includes `test_semantic_search_is_hard_scoped_to_clinic_and_audited`
(tenant isolation) and `test_ready_filter_excludes_stale_and_failed_embeddings`
(the two that fail on pgvector < 0.8). The feature is verified on 0.8.x; the
CI image pin is the only remaining step.

---

## 2. Headless `libGL.so.1` for open3d (environment note, no code change)

`open3d`'s `pybind` shared object links `libGL.so.1` for its **optional**
visualizer. The CPU registration/geometry paths never call into GL — the only
undefined GL symbols are three GLX entry points:

```
glXGetClientString  glXGetProcAddressARB  glXQueryVersion
```

On a headless image without `libgl1`, `import open3d` raises
`ImportError: libGL.so.1: cannot open shared object file`, which
`pytest.importorskip("open3d")` does **not** catch (it is an `ImportError`,
not `ModuleNotFoundError`), so
`tests/modules/dental_3d/test_registration_infrastructure.py::
test_open3d_registration_handles_deterministic_outliers` **fails** instead of
skipping.

Fix in CI/runtime images: install `libgl1` (Debian/Ubuntu) or use
`open3d-cpu` on an image that already provides it.

Verified in the sandbox by providing `libGL.so.1`:

```
tests/modules/dental_3d/test_registration_infrastructure.py .......  7 passed
```

Note this failure is **pre-existing on the untouched baseline** — it is not
caused by the consolidation.

---

## 3. Runtime smoke verification (performed)

The consolidated app was booted against the real database and exercised
over HTTP, which is as close to E2E as this environment allows:

- **Startup**: all 39 modules reconciled into `core_module`, schedulers
  registered, `Application startup complete`.
- **Route surface**: **377** OpenAPI paths served, including the newly
  integrated ones:
  - `/api/v1/copilot/clinical/{case-summary,report,second-review,treatment-suggestions,case-intelligence}`
  - `/api/v1/pathology_detection/{capabilities,patients/{id}/analyses,analyses/{id}}`
  - `/api/v1/orthodontic_planning/{capabilities,assessments,proposals,proposals/{id}/review,...}`
  - voice (16 paths), prescriptions (8 paths)
- **WhatsApp automation wired**: the scheduler logs
  `Added job "Process appointment messages (every 5 minutes)"`, confirming
  `process_appointment_message_automation` replaced the old reminder job.
- **AuthN enforced**: unauthenticated `POST /copilot/clinical/case-summary`
  and `GET /pathology_detection/capabilities` both return **401**.
- **Guardrail G4 confirmed at runtime**: with `ENVIRONMENT=development`,
  `/docs` -> 200; with `ENVIRONMENT=production`, `/docs` -> **404** and
  `/redoc` -> **404**, while `/health` stays 200.

Note: `/openapi.json` remains reachable in production. This is
**pre-existing baseline behaviour** — `backend/app/main.py` lines 73-74 are
byte-identical to the approved root `3a49246e` and only gate `docs_url` and
`redoc_url`. Flagged for the reviewer; not changed here because it is out of
scope for this consolidation.

One non-fatal startup error appears in the sandbox only:
`Frontend layer sync failed (non-fatal) ... PermissionError: '/host_frontend'`
— that path is a container mount point that does not exist here.

## 4. NOT verifiable in this environment

These remain unverified and must not be treated as production-validated:

- **Playwright E2E** — the browser CDN is unreachable from the sandbox
  (`Failed to download Chrome for Testing ... Download failure`), and the
  system font/dependency packages are unavailable. Run `npx playwright test`
  in CI.
- **WhatsApp production delivery** — requires live provider credentials.
- **Voice microphone / audio hardware** — unit tests only; no hardware.
- **Ollama end-to-end against a live server** — the donor's E2E harness was
  hard-bound to the replaced native `/api/chat` provider and was dropped;
  the canonical `/v1` provider retains unit coverage in
  `tests/test_ollama_provider.py`.
