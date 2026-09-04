# Multi-tenant resource isolation

How Dentora keeps one clinic from consuming shared resources (process,
DB pool, disk, outbox ticks, copilot streams) in a way that degrades
the others — and what was deliberately *not* built.

Deployment model this assumes: every clinic shares **one backend
process (single uvicorn worker), one Postgres database / engine, one
disk**. Row-level tenant separation (all queries filtered by
`clinic_id` via `ClinicContext` + RBAC) already existed and is out of
scope here; this document is about **resource** isolation only.

## The model (final)

| Layer | Control | Tenant-aware? | Where |
|---|---|---|---|
| Request rate | Fixed-window cap per tenant per minute (default 600), 429 + `Retry-After` | Yes — `clinic:<id>` from verified JWT, else `user:<sub>`, else IP | `app/core/tenant_limits.py` + middleware in `app/main.py` |
| Request concurrency | In-flight gauge per tenant (default 50), 429 past cap | Yes, same buckets | same |
| Public surfaces | Pre-existing slowapi IP limits (login, setup, booking, budget-public, whatsapp webhook) | No (unchanged) | `app/core/auth/router.py`, module routers |
| DB statements | `statement_timeout` 30s on every engine session | N/A (global safety net) | `app/database.py`, `DB_STATEMENT_TIMEOUT_MS` |
| DB pool | Shared 10 + 20, 30s checkout timeout | N/A — protected *via* the rows above | `app/database.py` (unchanged sizing) |
| Copilot streams | Max 5 concurrent SSE streams per clinic, 429 past cap, `finally` release | Yes | `app/modules/copilot/router.py`, `COPILOT_MAX_CONCURRENT_STREAMS_PER_CLINIC` |
| Copilot tokens | Monthly per-clinic token ceiling + 80% warning + `BudgetExceeded` turn event (pre-existing) | Yes | `app/modules/copilot/service.py` (`ClinicBudgetGuard`) |
| Agent actions | 10/min/session + 100 lifetime/session (lifetime counter fixed this phase; was dead config) | Per-session | `app/core/agents/guardrails.py` |
| Upload bytes | Streaming 1 MiB reads, 413 past `STORAGE_MAX_FILE_SIZE` (both media endpoints) | Cap is global; quota below is per-clinic | `app/modules/media/validation.py:read_capped_upload` |
| Stored bytes | Per-clinic quota (default 10 GiB, `None` disables), 413 with usage figures | Yes — `SUM(documents.file_size)` per clinic | `DocumentService.create_document`, `STORAGE_QUOTA_BYTES_PER_CLINIC` |
| Import uploads | Pre-existing: streamed 1 MiB chunks, 5 GiB cap, 413 + partial cleanup | Per-file | `app/modules/migration_import/router.py` (unchanged) |
| Outbox dispatch | Global 50/tick (pre-existing) **+ per-clinic 10/tick, oldest-first** (added) | Yes | `NotificationGateway.dispatch_outbox`, `NOTIFICATIONS_MAX_PER_CLINIC_PER_TICK` |
| Verifactu drain | Pre-existing: per-clinic advisory lock + 1000-batch + AEAT back-pressure | Yes | `app/modules/verifactu/services/submission_queue.py` (unchanged) |
| Background jobs | Pre-existing: per-clinic semaphore (5), own session, per-clinic try/except | Yes | `budget/tasks.py`, `copilot/tasks.py`, … (unchanged pattern) |
| Pagination | Pre-existing per-endpoint caps (`le=100/200/500` + service clamps) | N/A | module routers (unchanged) |
| Monitoring | Pre-existing: uptime-kuma (liveness) + per-clinic copilot usage endpoint | Partial | `monitoring/`, copilot metrics (unchanged) |

All knobs live in `app/config.py` (`TENANT_*`, `DB_STATEMENT_TIMEOUT_MS`,
`COPILOT_*`, `STORAGE_*`, `NOTIFICATIONS_*`) and are re-read per request,
so tests and operators can tune without restarts-in-code.

## Audit summary (what was found, per dimension)

1. **Tenant API rate limiting** — MISSING for authenticated traffic (slowapi
   was IP-keyed, production-only, public surfaces only). **Added**
   (`tenant_limits` middleware).
2. **Tenant concurrency limits** — MISSING. **Added** (same middleware,
   in-flight gauge).
3. **Background job isolation** — SUFFICIENT: per-clinic semaphore,
   per-clinic session + error isolation (budget/copilot tasks pattern).
   Not touched.
4. **Queue fairness** — Verifactu SUFFICIENT (per-clinic lock + batch);
   notifications outbox MISSING (global FIFO). **Added** per-clinic
   per-tick cap.
5. **DB query timeout** — MISSING (no `statement_timeout` anywhere).
   **Added** (30s server-side on all engine sessions).
6. **DB connection/pool controls** — shared pool by architecture (kept);
   protected indirectly via 1, 2, 5 + copilot stream cap. No per-tenant
   reservation possible without re-architecting the engine — explicitly
   out of scope, documented here instead.
7. **GraphQL depth/complexity** — N/A: no GraphQL in the tree.
8. **Pagination limits** — SUFFICIENT: caps on all sampled list
   endpoints; the one raw `.all()` found is per-parent bounded
   (budget items of one budget). Not touched.
9. **Storage quotas** — MISSING per-clinic (only a per-file setting that
   wasn't even enforced on actual bytes). **Added** byte-cap reads +
   per-clinic quota.
10. **AI resource quotas** — SUFFICIENT: per-clinic monthly token ceiling
    with lazy rollover + usage endpoint (pre-existing). Extended only
    with the stream-concurrency cap (dimension 2 applied to AI).
11. **3D/DICOM quotas** — N/A: no such subsystem exists.
12. **Tenant-scoped caching** — N/A: no cache layer exists; adding Redis
    would be a new dependency for zero current benefit.
13. **Per-tenant resource monitoring** — PARTIAL (uptime + copilot usage).
    No new dashboards: the 429s are JSON-logged via the standard access
    path and the copilot usage endpoint already exposes per-clinic AI
    burn. Deliberately not expanded (no metrics stack in the deployment).

## Correctness notes for reviewers

* The middleware resolves the tenant from the **verified** JWT
  (`decode_token`, app secret) — no DB lookup on the hot path; bad
  tokens fall back to the IP bucket (fail-open to coarser, never
  fail-closed). Health/docs/openapi paths are exempt.
* In-memory state (windows, gauges, stream counters) is correct for the
  shipped single-worker deployment and matches the existing guardrail
  posture. A multi-worker rollout needs a shared store — that migration
  is the only known scaling follow-up, not a defect.
* The guardrail lifetime counter fix changes no default behavior below
  100 lifetime actions/session; all 7 pre-existing guardrail tests pass
  unmodified.
* `statement_timeout` is 30s; the full backend suite (923 tests) plus
  the 22 new isolation tests run green against it, so no legitimate
  query is near the ceiling.

## Verification

`backend/tests/test_tenant_resource_isolation.py` (22 tests): key
resolution incl. fallbacks, rate/concurrency allow→deny→release,
true-overlap burst, disabled-flag passthrough, middleware 429 +
`Retry-After` through the real app, cross-tenant flood isolation,
health exemption, `statement_timeout` wiring, guardrail window-vs-total
regression, capped reads (unit + endpoint, adversarial oversize),
per-clinic quota allow→deny→other-clinic-unaffected, quota accounting,
stream saturation per clinic + slot release, outbox noisy-neighbour
fairness (25 vs 3 → 10 + 3 attempted).
