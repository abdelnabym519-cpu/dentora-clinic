# SECURITY / LOAD VERIFICATION — Audit, Gaps, Fixes, Evidence

Date: 2026-09-04. Branch: `arena/01a06b9e-dentora-clinic` (from `main @ 499dde00`,
prior phase closed at `fb58ec6`). Process followed:
Audit (read-only) → Gap Analysis → Implement genuine gaps only → Test →
Fix → Retest → Verify → Document → Commit → Push.

## 1. Audit — existing controls verified (run, not assumed)

382 route decorators mapped; every non-public route carries
`get_clinic_context` + `require_permission(...)`. Only intentional public
surfaces exist: auth setup/status, setup, login, refresh; license
status/activate/refresh; booking public slug endpoints (admin-chosen slug,
404 on unknown, `5/15minute` per IP); WhatsApp webhook (per-clinic HMAC);
budget public viewer (UUID token + DOB + signed cookie).

| Area | Control (verified in code) | Verdict |
|---|---|---|
| Passwords | bcrypt + strength rules on setup/create | Sufficient |
| JWT | 15 min access / 7 d refresh, `type` claim enforced, `token_version` revocation on deactivation | Sufficient |
| RBAC | Role→permission expansion, clinic membership scoping on all object reads (sampled: patients, documents, plans, budgets) | Sufficient |
| Tenant load | Per-tenant rate + concurrency middleware, streaming 413-capped uploads, 20/hr upload + 5 SSE caps, statement timeout + tuned pool, uvicorn header/body caps | Sufficient (prior phases) |
| SQLi | All `text()` uses bound params; pipeline `ORDER BY`/WHERE fragments are internal allow-list branches (`tab` 400-rejected otherwise, `page_size ≤ 100`); migration f-strings use module constants only | Sufficient |
| Public booking | Enabled flag, future-only, window bound, advisory-lock anti-double-book, finite slot inventory, IP throttle | Sufficient |
| Storage | Server-generated paths, MIME allowlist (no active types by default), attachment disposition on full downloads, per-clinic ownership on serve | Sufficient (+G3/G4) |
| Reports | Date-bounded aggregates (lifecycle capped at 365 d; billing bounded by statement timeout + tenant limits) | Sufficient |
| Outbound calls | Timeouts everywhere (AEAT 30 s, SMTP 30 s, Kapso 30 s, booking sync 10 s, license 5 s) | Sufficient |
| Secrets/PII | SMTP Fernet (SECRET_KEY-derived), no tokens/bodies/PHI in logs (IDs only), trial clock-pinning enforced in clinic context | Sufficient |
| License | Throttled server refresh, offline grace, enforcement-gated; prod composes set `ENVIRONMENT=production` so limiters are live | Sufficient |
| AI/Copilot | Auth + clinic context on SSE, per-clinic stream cap, token budgets, tool allow-list + registry chokepoint, transcript redaction default, prompt-injection guardrails | Sufficient |
| CORS / XSS | Reflect-only-allowlisted-origin; Vue auto-escaping + DOMPurify on Copilot markdown | Sufficient |
| DICOM/3D | No implementation exists in the tree | N-A |

## 2. Gap analysis — genuine gaps only

| # | Gap | Severity | Fix |
|---|---|---|---|
| G1 | Login had IP-only rate limiting (prod-only): distributed credential stuffing vs one account had no backoff; missing-user path skipped bcrypt (timing enumeration oracle) | Medium | Per-account exponential-backoff throttle (429 + `Retry-After`, capped 15 min, 24 h decay, reset on success) + dummy-hash constant-time path |
| G2 | No security-headers middleware: no `nosniff`, no frame options, full-URL referrers | Low | `security_headers_middleware` on every response incl. errors |
| G3 | Raw `original_filename` interpolated into `Content-Disposition` (quote breakout / CR-LF 500s) | Low | RFC 5987 helper `content_disposition_filename()` |
| G4 | `get_file_extension()` passed through `/` and unbounded length into storage paths (subdir escape / 500s) | Low | Sanitize to `[a-z0-9]`, max 10 chars |
| G5 | Refresh rotation without invalidation: superseded refresh tokens stayed valid 7 d; theft invisible | Medium | Server-side rotation chains: reuse-outside-grace ⇒ wipe all sessions; 60 s idempotent replay grace; legacy no-`jti` tokens adopted |

Accepted residuals (not gaps): unbounded billing-report ranges (killed at
30 s by statement timeout + tenant limits); OpenAI SDK default timeout
(contained by the 5-stream cap + token budgets); JS-readable auth cookies
(SPA Bearer architecture, mitigated by output encoding + sanitization);
`python-jose` maintenance status (functional with cryptography backend);
dev-compose limiters off (by design; prod enforced); public-booking
distributed flood (finite slot inventory by design).

## 3. Changes (this phase)

* `backend/app/core/auth/models.py` — `User.failed_login_attempts`,
  `User.failed_login_last_at`; `RefreshTokenChain` model + relationship.
* `backend/app/core/auth/service.py` — throttle policy
  (`LOGIN_FREE_ATTEMPTS=5`, capped exponential backoff, 24 h decay),
  `verify_password_constant_time()` + dummy hash, `jti` on refresh tokens.
* `backend/app/core/auth/refresh_chains.py` — **new**: chain
  create/consume/prune, replay grace, theft wipe, legacy adoption.
* `backend/app/core/auth/router.py` — login throttle + chain issuance;
  refresh chain enforcement; setup chain issuance.
* `backend/app/core/security_headers.py` — **new** middleware;
  registered in `backend/app/main.py`.
* `backend/app/modules/media/validation.py` — sanitized
  `get_file_extension()` + **new** `content_disposition_filename()`.
* `backend/app/modules/media/router.py` — download uses the helper.
* `backend/alembic/versions/0007_auth_hardening.py` — **new** migration
  (upgrade + downgrade both verified against scratch Postgres).
* `backend/tests/test_security_hardening.py` — **new**: 11 adversarial tests.

## 4. Test evidence

* New: `tests/test_security_hardening.py` — 11/11 pass (throttle 429 +
  `Retry-After`, throttle-during-correct-password, counter reset, unknown
  email always 401, backoff decay unit, rotation → replay → reuse-revokes-all
  → relogin, legacy adoption, headers on 200 + 404, disposition breakout +
  unicode, extension sanitization).
* Existing auth: `tests/test_auth.py` — 9/9 pass (no regressions in
  setup/login/me flows).
* Migration: `upgrade heads` applies `0006 → 0007` (columns + table
  present); targeted `downgrade 0006` removes both; re-upgrade restores.
  (Full `downgrade base` is blocked by pre-existing one-way `tp_0004`,
  covered by the `ONE_WAY_REVISIONS` degraded path — pre-existing, N-A.)
* Full suite: **948 passed, 8 deselected, 0 failed** (~29 min).
* Targeted post-format re-run (`test_security_hardening`,
  `test_auth`, `test_media_photos`): **28 passed**.
* `ruff check backend/`: clean. `ruff format --check` on all touched
  files: clean.
* Frontend `npm run lint`: 0 errors, 4 warnings — all pre-existing
  `vue/no-v-html` notes in untouched odontogram components.
* `generate_catalogs.py --check`: exit 0.
