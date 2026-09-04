# Full Testing / CI — closure report

**Phase:** Full Testing / CI · **Status:** CLOSED ✅
**Validated tree:** `main` @ `499dde00` (session branch `arena/01a06b9e-dentora-clinic`,
no code changes required — see §7)
**Validation date:** 2026-09-04 · **Environment:** Debian 12 sandbox, Python 3.11,
Node v22, PostgreSQL 16.2 (pip-bundled, see §5), zero code diff vs `main`.

> Note on branch naming: the phase brief referenced `integration/dentora-canonical`
> @ `4e529331`. That ref does not exist in this clone (only `main` + the session
> branch). All validation below ran against the actual checkout (`499dde00`),
> on the session-fixed branch per workspace policy. Totals therefore describe
> this tree, not the numbers quoted in the brief.

## 1. Gates and results

| Gate (CI job / command) | Result |
|---|---|
| Backend pytest, default set (`backend/`, `python -m pytest`) | **915 passed, 0 failed** (8 round-trip marks deselected) |
| Alembic round-trip (`pytest -m alembic_roundtrip`) | **8 passed, 0 failed** |
| Manifest consistency (subset of the above, no DB) | passed (included in the 915) |
| `alembic upgrade heads` on a fresh database | **70 revisions, exit 0**, one head per branch |
| Ruff `check` + `format --check` on `backend/` | **0 errors, 601 files formatted** |
| Frontend vitest (`npx vitest run`) | **9 files, 71 tests, all passed** |
| Frontend ESLint (`npm run lint`) | **0 errors** (4 pre-existing `vue/no-v-html` warnings) |
| Frontend typecheck gate (`nuxi prepare`, as CI runs it) | **exit 0, types generated** |
| Docs layout (`scripts/check_docs_layout.py`) | **OK** |
| Catalog freshness (`generate_catalogs.py --check`) | **exit 0** |
| Docs coverage (`check_docs_coverage.py --strict`) | **PASS, 0 errors** (32 informational warnings) |
| Docs portal build (`vitepress build` + `dist/index.html` check) | **exit 0, DIST_OK** |
| AI safety cluster (gateway, orchestrator, agents, copilot, clinical_notes — 12 files) | **78 passed, 0 failed** |
| AI gateway client (`test_ai_gateway_client.py`) | **7 passed** |
| Agent guardrails (`test_agents_guardrails.py`: approval gates, RBAC chokepoint, rate limits) | **7 passed** |
| Live-stack smoke (migrated DB → uvicorn `:8100` → setup → login → `/me` → patient create/list; Nuxt dev `:3000/login` → 200) | **all green** |
| Playwright `--list` (spec enumeration, no browser needed) | **24 tests in 6 files enumerate** |
| Playwright browser execution | **environment-blocked**, see §4 |

**Backend total: 923 passed (915 default + 8 round-trip), 0 failed, 0 errors.**

## 2. What was fixed

**No repository code was changed.** Two failures surfaced during the run; both were
investigated and both turned out to be environment/invocation issues, fixed
environment-side with zero diff to the tree (`git status` clean apart from this file):

1. **`test_every_shipped_module_passes_validation` failed when pytest was launched
   from the repo root** (`REMOVABLE_BRANCH_NOT_ISOLATED: booking`). Reproduced in
   isolation: fails from repo root, passes from `backend/`. Root cause is
   CWD-sensitive module/migration discovery (`DENTORA_DEV_MODULE_SCAN` filesystem
   fallback + path-relative branch isolation check). CI runs with
   `working-directory: backend`, and the documented workflow (`CLAUDE.md`
   quickstart, `docker-compose exec backend python -m pytest`) does the same —
   from there the full suite is green. Changing discovery semantics to be CWD-proof
   would touch the plugin-system contract, so per minimal-fix policy this is
   **documented, not changed**: the suite must be run from `backend/`.
2. **Alembic round-trip selection failed first run: `alembic`/`pg_dump` not on
   `PATH`.** Fixed by exporting the venv bin + bundled-Postgres bin dirs. No code
   impact. (CI images have these on `PATH` already.)

## 3. Final test totals

- Backend: **923 passed, 0 failed** (915 default + 8 `alembic_roundtrip`)
- Frontend vitest: **71 passed** (9 files)
- AI safety cluster: **78 passed** (subset of backend total; gateway 7/7, guardrails 7/7)
- Ruff: 0 errors · ESLint: 0 errors · `nuxi prepare`: exit 0
- Docs gates (layout / catalogs / coverage-strict / portal build): all pass
- Playwright: 24/24 enumerate; 0 executed in-browser (blocked, §4)

## 4. Remaining blockers (none are code)

1. **Playwright browser execution — environment-blocked (external CDN).**
   `npx playwright install chromium` fails: `cdn.playwright.dev` is unreachable
   from this sandbox (TLS reset; `curl` → `000`), both primary and Microsoft
   fallback hosts. No system browser exists and `apt` sources are unreachable, so
   no Chromium can be provisioned here. Mitigation actually performed: spec
   enumeration passes (24 tests), and the exact stack E2E would drive was
   validated live (API `:8100` healthy, Nuxt `:3000/login` → 200, setup/login/
   patient CRUD through real HTTP). **External validation required:** run the
   `e2e` CI job (GitHub Actions, `./scripts/e2e.sh`) where browser download works.
2. **Ollama /v1 E2E — not applicable to this tree (external runtime + deferred scope).**
   v1 ships an **OpenAI-only** provider by explicit design
   (`backend/app/core/llm/factory.py`, `docs/technical/copilot-agentic-architecture.md`
   §5: *"Deferred: … self-hosted/Ollama provider"*). No Ollama code, config, or
   test exists here; LLM tests use scripted fake providers by design (no network).
   Closest in-repo coverage is green (gateway 7/7, orchestrator included in the 78,
   live API smoke). A live-Ollama E2E can only run where an Ollama runtime exists —
   external validation, deferred by architecture, not by failure.
3. **Full strict `nuxt typecheck` (vue-tsc) — not a CI gate, pre-existing debt.**
   CI's `frontend-typecheck` job runs only `nuxi prepare` (green). A local full
   `nuxt typecheck` reports ~224 strictness-level items (readonly response-type
   mismatches, layer-optional chaining) across host + layer components. These are
   type-level, runtime-healthy (live smoke green), and fixing them file-by-file
   would exceed minimal-fix scope — recorded here as known debt, no action taken.

## 5. Sandbox environment notes (reproducibility, not repo changes)

`apt` and most binary CDNs are egress-blocked here, so the database was provided as:
pip `pgserver` (PostgreSQL 16.2) data dir at `/tmp/dentora-pg`, TCP `127.0.0.1:5433`,
databases `dental_clinic_test` (pytest) and `dentora_smoke` (live stack). The bundle
lacks the `pgcrypto` contrib module required by budget migration `bud_0002`, so
`pgcrypto` was compiled from the `REL_16_2` sources against a source-built OpenSSL
3.0 (`/tmp/ossl30`, RUNPATH-baked) and installed into the bundle; `gen_random_uuid()`
verified. All of this lives outside the repo — the validated tree is byte-identical
to `main` plus this document.

Canonical commands (from `backend/` unless noted):

```bash
export DATABASE_URL="postgresql+asyncpg://postgres:testpass@127.0.0.1:5433/dental_clinic_test"
export SECRET_KEY="test-secret-key-for-ci" ENVIRONMENT="test" TESTING="true"
python -m pytest -q                     # 915 passed
python -m pytest -m alembic_roundtrip   # 8 passed (needs alembic+pg_dump on PATH)
ruff check backend/ && ruff format --check backend/
cd ../frontend && npx vitest run && npm run lint
```

## 6. Phase determination

Every required validation that can run in this environment was run and is green;
the two items that cannot run here are blocked by sandbox egress / missing external
runtimes, are **not code failures**, have documented mitigations above, and both
have a standing external gate (GitHub Actions `e2e` job; future Ollama runtime).
The phase is therefore legitimately closed with deferred external validation noted.

**FULL TESTING / CI — CLOSED ✅**
