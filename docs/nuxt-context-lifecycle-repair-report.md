# Dentora — Nuxt Context / Composable Lifecycle Repair

**Branch:** `arena/01a091f7-dentora-clinic` (pushed) · **Base:** `f1c79ca` (`main`)
**Commits (5):** `e6f92f6` → `3f1b816` → `61fea71` → `65f3390` → `5bed85d`
**Files (11):** 6 application sources + 5 test files · **+1273 / −65**, plus this document
**Verification:** eslint clean over all of `app` + `tests` · `nuxt typecheck` clean · **363/363 frontend tests** · production build clean · live Nuxt/Nitro SSR A/B against a stub API
**Status:** everything below is CODE-VERIFIED or ARENA-SANDBOX-VERIFIED. A Docker container, a browser and Ollama cannot run in this sandbox — see §7.

---

## 1. Executive summary

The reported symptom —

```
ERROR  Failed to fetch clinic: "A composable that requires access to the Nuxt
       instance was called outside of a plugin, Nuxt hook, Nuxt middleware, or
       Vue setup function."
WARN   useModules: backend fetch failed — <same message>
       Clicking items in the Patients UI produces "Patients connection error"
```

— was **not** a backend failure, and not a Docker, `API_BASE_URL`, CORS or AI-layer problem. It was a **Nuxt instance lifecycle violation inside `useApi`'s request function**, which three separate `catch` blocks then *relabelled* as a connectivity problem:

| What the log said | What actually happened |
| --- | --- |
| `Failed to fetch clinic: <NUXT_E1001>` | `useClinic.fetchClinic()` never reached the network. Its `catch` printed the context violation as if the backend had failed. |
| `useModules: backend fetch failed — <NUXT_E1001>` | `useModules.ensureLoaded()` likewise. The sidebar degraded to host entries. |
| `Patients connection error` | The Patients screen received the same thrown error and rendered it as an outage — against a healthy backend. |

Three distinct violations were found by the audit and all three are fixed. The first is the cause of the messages above.

> **If you are still seeing this error, your container is built from `main`.** `main` (`f1c79ca`) contains all three violations; the fixes exist only on `arena/01a091f7-dentora-clinic`. §7 has a one-command self-check and the rebuild recipe.

---

## 2. Root cause (traced, not assumed)

### 2.1 The call chain

```
layouts/default.vue:6        useModules() → ensureLoaded()   (route changes)
patients/index.vue:104       api.get('/api/v1/patients?…')   (list load)
useClinic.ts:159             watch(auth.isAuthenticated, …, { immediate: true })
  └─ useClinic.ts:22         fetchClinic() → api.get('/api/v1/auth/clinics')
       └─ useApi.ts          $api(path, options)
            └─ origin/main useApi.ts:66
                 const selected = useSelectedClinicId()      ← THROWS
                   → useCookie('clinic_id')
                     → (server) useRequestEvent() → useNuxtApp()
```

Every one of those callers is a **deferred context**: a watcher callback, an `onMounted` continuation, a route-change handler. `$api` is the single function they all funnel through, and it acquired an instance-bound composable **per request** instead of once at setup.

### 2.2 Why that throws — from the installed sources

* `node_modules/unctx/dist/index.mjs:60-76` — `callAsync` sets `currentInstance`, invokes the callback, then **clears it synchronously** (`currentInstance = void 0`, lines 69-71) the moment the callback returns its promise, unless a prior `set()` marked the context as a singleton.
* `node_modules/unctx/dist/index.mjs:97-118` — the instance is restored only through `executeAsync` / `withAsyncContext`. Nuxt applies that transform **only to the bodies it owns**: `defineNuxtPlugin`, `defineNuxtRouteMiddleware` and `setup`. An ordinary `async function` such as `$api` or `fetchClinic` is not transformed, so its post-`await` continuation runs with **no instance**.
* `unctx`'s `use()` (lines 28-34) then throws `Context is not available`, which Nuxt surfaces as **`NUXT_E1001`**.

### 2.3 Why SSR fails and the browser hides it

`node_modules/nuxt/dist/app/nuxt.js`:

* **line 221** — `if (import.meta.server) return nuxt.vueApp.runWithContext(() => nuxtAppCtx.callAsync(nuxt, fn))` → server: cleared on suspend.
* **line 223** — `nuxtAppCtx.set(nuxt)` → client: persistent, so deferred calls keep working.

That asymmetry is why the defect survived: in the browser nothing throws, while every server-side render does — and the failed SSR state is what the client then displays.

### 2.4 About `useApi.ts:151`

Line 151 is **not** a composable call in any version of that file:

| Revision | source line 151 | any composable within 149–153 |
| --- | --- | --- |
| `origin/main` (189 lines) | `}` | none — the only acquisition is line 66, inside `$api` |
| `e6f92f6`, `84f7240`, `cab1372` | a comment line | none |
| `3f1b816` → `5bed85d` | blank | none |

Only **four** revisions of `frontend/app/composables/useApi.ts` exist across all refs in the repository, and none has an instance composable near line 151. The Vite-transformed module was also inspected directly from a live dev server (`/_nuxt/@fs/…/useApi.ts`): `useSelectedClinicId()` lands at transformed line **38**, and line 151 is `return {`.

Conclusion: `:151` is a bundler/transform line number, not a source line. The enclosing **function** is nonetheless unambiguous — `$api` — and its per-request `useSelectedClinicId()` is the only instance acquisition that file has ever contained.

### 2.5 The two further violations found by the same audit

**(b) Component-instance-bound i18n in plugin-reachable code.** `useApi` took translations from vue-i18n's `useI18n()` (`origin/main useApi.ts:37`), which resolves the *current component instance*. On `main` this is harmless because `app/plugins/settings.registry.ts` calls `useClinic()` lazily, from inside a page's computed. The moment the clinic acquisition is hoisted into the plugin (which `e6f92f6` correctly did, to stop a fresh `watch` per evaluation), `useI18n()` executes at plugin scope and **every SSR render 500s**:

```
message: "Must be called at the top of a `setup` function"
  at useI18n (vue-i18n)  →  at useApi (useApi.ts)  →  at useClinic (useClinic.ts)
  at app/plugins/settings.registry.ts:26
```

Reproduced in this sandbox: with `main`'s `useApi.ts` and the fixed plugin, `GET /login` returns **500**. A container built from the intermediate range `e6f92f6..cab1372` therefore 500s on *every* page; only `3f1b816` and later are clean.

**(c) Instance composables acquired after an `await` in route middleware.** `origin/main auth.global.ts:53` awaits `getCommercialLicenseStatus()` and only then calls `useRuntimeConfig()` (line 77) and `useAuth()` (line 85); both module-level helpers also resolved runtime config themselves (lines 17, 32). This is what Nuxt's documentation forbids, and it is fixed by hoisting.

*Honest qualification:* bisection on a live server showed (c) does **not** throw in the shipped runtime, because a `defineNuxtRouteMiddleware` body **is** transformed, so unctx restores the instance across its awaits. Fixing it is hardening to the documented contract — it is not the cause of the reported messages, and it is labelled as such in the commit message and in §5.2.

---

## 3. What was fixed, by commit

### 3.1 `e6f92f6` — capture Nuxt-instance composables at setup, not per request (4 files)

`useApi.ts`: `const selectedClinicId = useSelectedClinicId()` now runs **once**, at setup (line 109), and `$api` reads `selectedClinicId.value` per request (line 145). `useAuth.ts`: five deferred functions converted the same way. `plugins/settings.registry.ts`: `useClinic()` acquired once during plugin setup instead of inside onboarding predicates, which also stopped a fresh `watch(auth.isAuthenticated, …, { immediate: true })` — and therefore a fresh `GET /api/v1/auth/clinics` — on every evaluation of the getting-started computed. Adds `tests/composables/deferredNuxtContext.test.ts`.

A secondary benefit: one `useCookie` ref instead of one per request stops leaking a `BroadcastChannel` per request, whose `onScopeDispose` cleanup never runs when the ref is created outside an effect scope.

### 3.2 `3f1b816` — make SSR-boot composables context-safe (7 files)

* **New** `app/utils/i18nScope.ts` → `useGlobalT()`: reads the global scope from `useNuxtApp().$i18n`, which is the same scope `useI18n()` returns when called with no options, but needs only the Nuxt instance — so it works in components, plugins, middleware and composables alike. Locale reactivity is unchanged.
* `useApi.ts` and `useClinic.ts` now use `useGlobalT()` instead of `useI18n()`.
* `middleware/auth.global.ts`: `useRuntimeConfig()`, the derived `baseURL`, `useAuth()` and the licence `useState` are all acquired **above the first `await`**; `isSystemInitialized(baseURL)` and `getCommercialLicenseStatus(baseURL)` take the URL from the caller instead of resolving config themselves. Gate order, redirects and the position of `auth.init()` are unchanged.
* Adds `tests/middleware/authGlobal.context.test.ts` and `tests/composables/pluginContextI18n.test.ts`, and the static gate `tests/architecture/nuxtContextSafety.test.ts`.

### 3.3 `61fea71` — reproduce the reported failure and pin the fix (1 file)

`tests/composables/deferredClinicFetch.test.ts` arms a suspended instance (the `useCookie` mock throws once `suspended` is set) and asserts: `GET /api/v1/auth/clinics` is really sent, carrying `Authorization` **and** `X-Clinic-Id` from the captured ref, with no `Failed to fetch clinic` logged; `GET /api/v1/modules/-/active` is really sent from a layout-shaped deferred call with no `useModules: backend fetch failed` logged; and a genuine 503 is **still** logged with the server's reason and **still** leaves `currentClinic` null.

### 3.4 `65f3390` — extend the gate to `.vue` files (1 file)

The gate walked only `.ts`, leaving the largest surface in the app unpoliced. New rule: no instance composable inside a deferred callback (`setTimeout`, `setInterval`, `requestAnimationFrame`, `queueMicrotask`, `addEventListener`, `nuxtApp.hook`, `then`/`catch`/`finally`, `once`, `subscribe`) and none at module scope of a non-setup `<script>` block. Line numbers are offset back to the real `.vue` line.

### 3.5 `5bed85d` — widen the gate to every `.ts` under `app/` and the module layers (1 file)

The `.ts` walk was a whitelist of subdirectories, so a module's `lib/`, `components/`, `config/` and page helpers were never parsed — eleven `dental_3d`/`orthodontic_simulator` `lib/` files and three module `components/` files sat outside it. Now every `.ts` under `frontend/app` and `frontend/module_layers` (the tracked symlink to `backend/app/modules`) is parsed, skipping only directories that cannot contain app code. There is no Nitro `server/` tree in this repo, so no host-context files are swept in.

---

## 4. Why this is the architecturally correct fix

It corrects **ownership and lifetime** to match how Nuxt actually works, rather than suppressing a symptom:

1. **A composable that hands out a deferred function must acquire its instance-bound dependencies during setup** and read them afterwards. That is exactly the pattern `useApiHeaders()` already used, and it is what Nuxt's own docs prescribe. The refs are `useState`/`useCookie`-backed, so reactivity across clinic switches and login transitions is preserved — nothing is cached stale.
2. **A plugin must use app-scoped services, not component-scoped ones.** `$i18n` is the documented acquisition point outside `setup`; `useI18n()` is not.
3. **Middleware acquires before it awaits**, which is the documented contract and keeps SSR and client behaviour identical.

Nothing was masked to get there: no fallback values, no `try/catch` that swallows, no hardcoded clinic/patient/module data, no auth or RBAC change, no health check disabled. A real 503 is still reported with the server's own reason and still leaves the state empty — asserted by §3.3's third test.

---

## 5. Verification

### 5.1 Live SSR A/B — the decisive evidence

A real Nuxt dev server (`Nuxt 4.5.2 / Nitro 2.13.4 / Vite 8.2.2`) was run against a throwaway stub API in `/tmp` (never committed), with 250 ms latency so continuations land outside the render's context window. Both revisions were exercised on the **same** server, same stub, same cookies:

| | `origin/main` (the code your container builds) | `HEAD` (fixed) |
| --- | --- | --- |
| `GET /patients` | 200 | 200 |
| `GET /settings` | 200 | 200 |
| **`NUXT_E1001` emitted** | **1** | **0** |

On the fixed tree the stub's request log shows the whole chain arriving, each call carrying `Authorization` **and** `x-clinic-id`:

```
GET /api/v1/license/status
GET /api/v1/auth/me            auth=Bearer …  clinic=6f1c2d34-…
GET /api/v1/auth/clinics       auth=Bearer …  clinic=6f1c2d34-…
GET /api/v1/modules/-/active   auth=Bearer …  clinic=6f1c2d34-…
GET /api/v1/patients           auth=Bearer …  clinic=6f1c2d34-…
```

Server-rendered HTML on the fixed tree contains `Demo Clinic` and `Demo Dentist` (real backend data reaching the UI during SSR) and, on `/settings`, all eight registry-driven category links — the registry populated by the plugin that used to 500 the render.

### 5.2 Regression tests — each validated red against the pre-fix code

| Suite | Result | Red validation |
| --- | --- | --- |
| `deferredClinicFetch.test.ts` | 3/3 | Against `main`'s `useApi.ts` with *only* the i18n line corrected (isolating violation (a)): `$fetch` called **0 times** — the request never left the process — and **both** `Failed to fetch clinic` and `useModules: backend fetch failed` were logged. The genuine-503 test still passed, proving error handling was not weakened. |
| `pluginContextI18n.test.ts` | 6/6 | 4/6 fail pre-fix with `Must be called at the top of a 'setup' function`. |
| `authGlobal.context.test.ts` | 6/6 | 5/6 fail pre-fix with the exact `NUXT_E1001` message. This suite models the **stricter** contract from §2.5(c) — it simulates suspension without unctx's transform-based restore — so it is a contract test, not a reproduction of a shipped failure. |
| `deferredNuxtContext.test.ts` | pass | Pre-existing suite from `e6f92f6`. |

### 5.3 The static gate (`tests/architecture/nuxtContextSafety.test.ts`)

Five tests over the real source, parsed with the TypeScript compiler API. Three rules, each verified to flag the exact pre-fix defect site so none is vacuous:

| Rule | Flags on pre-fix code |
| --- | --- |
| Component-instance API reachable from a plugin or middleware (function-level reachability) | `useApi.ts:88 useI18n()` |
| Nuxt-instance composable acquired after an `await` | `auth.global.ts:77 useRuntimeConfig()`, `:85 useAuth()` |
| Re-acquisition inside a deferred helper function | `useApi.ts:96 re-acquires useSelectedClinicId()` |
| Instance composable inside a deferred callback / module scope in `.vue` | synthetic probe: `setTimeout(() => { useRuntimeConfig(); useI18n() })` flagged on the correct real lines (5, 6), while the legitimate top-level `<script setup>` acquisition on line 3 was **not** flagged |

Coverage guards assert the walks cannot silently degrade to nothing and still pass.

### 5.4 Full gate set

| Gate | Result |
| --- | --- |
| Frontend suite | **363/363 passed, 0 failed** |
| eslint over all of `app` + `tests` | clean |
| `nuxt typecheck` | clean |
| Production build (`npm run build`) | clean, 24 MB / 4.58 MB gzip |
| Static sweep | **0 violations across 200 `.ts` + 320 `.vue` files** |

---

## 6. What was audited and found clean

Traced explicitly for this mission, all acquisitions at a valid context:

* **Patients page** (`backend/app/modules/patients/frontend/pages/patients/index.vue`): `useI18n()` (32), `useApi()` (33), `useToast()` (34), `useRouter()` (35), `useRoute()` (36), `usePermissions()` (37) — all at `<script setup>` top level. Its `onMounted` (189) only opens the create-patient modal; the list load (104) uses the `api` captured in setup. The page itself was never at fault — it inherited `$api`'s violation.
* **`useModules`**: acquires `useI18n`/`usePermissions`/`useAuth`/`useApi` at setup (35-38); `ensureLoaded` (45-73) uses the captured `api`; called from `layouts/default.vue:6` and `pages/settings/modules/index.vue:8`, both component setups.
* **`useClinic`**: `fetchClinic` (22) uses the captured `api`; the `immediate` watcher (159) is the trigger that surfaced the defect.
* **`middleware/auth.ts`** (the named, non-global middleware): `useAuth()` at line 2, before its `await` at line 5; afterwards it only reads `auth.isAuthenticated.value`. Clean.
* **Plugins**: only four exist (`locale.client`, `locale.server`, `nprogress.client`, `settings.registry`). `nprogress.client` calls `useRouter()` at plugin top level — valid.
* **Module layers**: all 34, through the `frontend/module_layers` symlink. The `lib/` files are pure geometry/scene code with zero composable usage.

---

## 7. LOCAL RUNTIME VERIFICATION REQUIRED

### 7.1 Why the error persists locally

`main` (`f1c79ca`) still contains all three violations — `useApi.ts:66` (`useSelectedClinicId()` inside `$api`), `useApi.ts:37` (`useI18n()`), `auth.global.ts:53→77,85`. The fixes live only on `arena/01a091f7-dentora-clinic`. Rebuilding the frontend image from `main` reproduces the error forever, no matter how many times the container is rebuilt.

Note also that a container built from the intermediate range `e6f92f6..cab1372` would 500 on **every** page (§2.5(b)). Use `3f1b816` or later.

### 7.2 One-command self-check

```powershell
Select-String -Path frontend\app\composables\useApi.ts -Pattern "useSelectedClinicId|useI18n|useGlobalT"
```

| Output | Meaning |
| --- | --- |
| `const selectedClinicId = useSelectedClinicId()` near the top of `useApi()`, plus `const t = useGlobalT()` | **Fixed** — rebuild the image |
| `const selected = useSelectedClinicId()` inside `$api`, or `const { t } = useI18n()` | **Unfixed** — this is the source of your error |

### 7.3 Getting the fix into your build

**Option A — build from the branch:**

```powershell
cd C:\path\to\dentora-clinic
git fetch origin
git checkout arena/01a091f7-dentora-clinic
git pull --ff-only origin arena/01a091f7-dentora-clinic
git log --oneline -1     # EXPECT: 5bed85d test(frontend): widen the context gate …
```

**Option B — cherry-pick only the lifecycle work onto your own branch** (five commits, eleven files, no merge to `main`):

```powershell
git fetch origin
git cherry-pick e6f92f6 3f1b816 61fea71 65f3390 5bed85d
```

**Then rebuild and restart (never `down -v`):**

```powershell
docker compose build frontend
docker compose up -d frontend
```

### 7.4 Post-rebuild checks, in order

```powershell
docker compose logs --tail=200 frontend | Select-String "NUXT_E1001","Failed to fetch clinic","useModules: backend fetch failed","Must be called at the top"
```
**EXPECTED:** no matches.

```powershell
(Invoke-WebRequest http://localhost:3000/login -UseBasicParsing).StatusCode
```
**EXPECTED:** `200`. A `500` here means the old image is still running.

Then in the browser: log in → **Patients** → click through patients and features. **EXPECTED:** no `Patients connection error`, DevTools console free of those messages, and the sidebar showing module navigation (proof `/modules/-/active` succeeded).

Finally, for the AI features this unblocks:

```powershell
ollama list
```
**EXPECTED:** the model named in your `.env`. Then open a real patient/case → **AI Case Summary → Generate** → a real result renders.

---

## 8. Constraints honoured (explicit non-changes)

No merge to `main`; no force push; no history rewrite; no DB reset, drop or volume removal; no AI module provisioning change; no revert of any AI activation fix; no RBAC, permission, doctor-approval or Clinical Safety Governor change; no fake or hardcoded clinic/patient/module data; no weakened validation or error handling; no removed tests; no Docker/`API_BASE_URL`/CORS change; cancelled Dental Radiograph Intelligence scope untouched; Clean Architecture and module boundaries intact.

`frontend/modules.json` is a backend-generated artifact and was **not** committed in a rewritten form: it was temporarily regenerated with host paths to run the local gates (the committed copy lists 20 layers and omits `verifactu`, so `npm test` on a fresh clone needs `python -m app.cli modules sync-frontend` first — that requires the database, which this sandbox does not have), then reverted. `frontend/.nuxtrc`, which test runs rewrite, was reverted likewise.
