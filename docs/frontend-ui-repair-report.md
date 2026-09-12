# Dentora — Frontend / UI Functionality & Interaction Repair

**Branch:** `arena/01a091f7-dentora-clinic` (pushed) · **Base:** `f1c79ca` (`main`)
**Code commits (21):** `45f7740` → `b0fb6d6` → `40c767c` → `6025974` → `64e6d40` → `7960143` → `ef76ede` → `085d0f4` → `20c3199` → `1601c7e` → `d51023e` → `eaa6330` → `8dbbda6` → `2aaff85` → `faca30e` → `0b2a663` → `e95ebd6` → `b47dc1c` → `4de533c` → `cd57e2c` → `4eb5539`
**Cumulative diff (the 21 code commits):** **226 files changed, +9667 / −1043**, plus this document
**Verification:** vue-tsc clean (app + all 27 module layers) · eslint clean · **53 test files / 328 tests pass, 0 unhandled errors** · production build succeeds · the built server bundle imports cleanly
**Status:** everything below is CODE-VERIFIED. Browser/E2E and live-backend runs are impossible in this sandbox — see §7.

---

## 1. Executive summary

The reported symptom — *"Permission denied: verifactu.settings.read"* / a misleading **Access Denied** when clicking unrelated areas (patients, AI), with the page often opening fine afterwards — was **not** a Verifactu bug and not a patients/AI bug. It was a **global error-handling defect** plus an **ambient background probe**:

1. `useApi` turned *every* HTTP 403 from *any* request into one global, context-free "Access denied" toast — including requests the user never made.
2. A Veri*Factu compliance probe (`RejectedGlobalBanner`'s health poll, mounted on every default-layout screen, plus the client slot plugin) ran **for every signed-in user**, gated on the **wrong permission set**: the endpoint requires `verifactu.settings.read`, the component checked `verifactu.queue.manage` / `verifactu.records.read`. Dentists and receptionists hold only `records.read`, so they earned a guaranteed 403 **every 60 seconds, on every screen, forever**.
3. Because the probe is unrelated to the page's own data, the page still loaded — hence "the error appears, then the page opens successfully".

Both halves were fixed at the source (§3.1). The audit then found the same two defect classes — *errors reported in the wrong place* and *failures that render as empty states* — across the app, plus classes that only show up in real use:

* **Requests that silently lost the clinic selection** — thirteen blob/stream/export calls sent `Authorization` without `X-Clinic-Id`, so the backend resolved *another clinic's* role for a multi-clinic user. Nothing errored, which is why it survived (§3.4).
* **Destructive buttons that silently do nothing inside an iframe** — `window.confirm` is blocked there, so the handler returned early and the click was a no-op (§3.4).
* **A patient-facing page that spins forever when its load fails** — the public budget link (§3.5).
* **A failure rendered as a clinical or financial claim** — "no notes for this appointment", "No payments", a WhatsApp settings form built from blanks with a live Save, a report showing a green *"No overdue invoices"* to a receptionist who simply lacked `reports.billing.read`, an odontogram rendering a **clean mouth** because the treatment read failed (§3.6, §3.7, §3.11, §3.20).
* **A build-level crash on an AI page** — an undici override that broke `isomorphic-dompurify`, so server-rendering `/copilot` died during module load (§3.8).
* **Stale responses** — every list and record is re-fetched by a watcher on whatever the user just changed, and *none* of those fetchers checked whether they were still the newest. Patient A's odontogram under patient B's name; the previous day's bookable slots; treatments that do not match the search box, one click from being added to a plan (§3.12–§3.14, §3.16, §3.18).
* **User input destroyed by a failure the user did not cause** — the Copilot composer clearing the message before sending (§3.11), and the periodontogram close dialog wiping the clinician's observations before the request resolved (§3.21).
* **Writes that could be submitted twice** — three clicks on the override Save produced **three** overrides for the same dates; a re-entered SMTP save could store a half-applied password (§3.15, §3.17, §3.19).
* **Surfaces a keyboard cannot use, and menus that will not dismiss** — the clinic switcher had no keyboard path at all; the prescriptions patient picker had no Escape; a patient's invoice rows were click-only (§3.17, §3.18).

Every fix carries a regression test, and **every regression test was verified to fail with its fix removed** — the failure output is quoted in §3 wherever it is the interesting part of the evidence.

**No permission was granted, no RBAC rule weakened, no 403 converted into a success, no genuine Veri*Factu error hidden on a Veri*Factu screen, no test deleted, `main` and PR #65 untouched.**

---

## 2. Root cause of the reported symptom (traced, not assumed)

The symptom is two independent defects that only look like one, plus a third that made it intermittent.

**(a) One global toast spoke for every request.** `useApi` had a single catch-all notification path: any 403, from any module, from any request — including background probes the user never initiated — produced the same context-free *"Access denied"*. There was no notion of *which operation* failed, so the toast was attributed by the user to whatever they had just clicked.

**(b) An ambient probe was guaranteed to be denied.** `RejectedGlobalBanner` is mounted on every default-layout screen and polled `GET /api/v1/verifactu/health` every 60 s. The endpoint requires `verifactu.settings.read`; the component gated on `verifactu.queue.manage` / `verifactu.records.read`. Any role that could see the banner but lacked `settings.read` — dentists, receptionists — produced a 403 on every tick, on every page. Combined with (a), that is a recurring *"Permission denied: verifactu.settings.read"* over an unrelated screen.

**(c) Why the page still opened.** The probe has nothing to do with the page's own data, so the page's requests succeeded and it rendered normally. The error and the working page are two different request streams — which is exactly the "error appears, then the page opens successfully" report.

**(d) Why it was intermittent across reloads.** `useAuth` fetched `/auth/me` **without** `X-Clinic-Id`. The backend's `select_clinic` then fell back to the user's alphabetically-first membership, so a multi-clinic user could be granted *another clinic's* permission set after a reload — producing spurious denials until the selection self-repaired (and, separately, per-clinic documents on the wrong letterhead).

**What was changed, and what was deliberately not:**

* `useApi` gained per-request `silent` and `operation` options. The shared toast now names the failing operation and its cause — a 403 reports the missing permission, 5xx/network report the server's detail. 404/409/422 are never toasted (callers render them inline). Identical notifications are de-duplicated in a 5 s window so a polling probe cannot stack toasts. **Errors are still thrown**: nothing is swallowed and no 403 is converted into success.
* The Veri*Factu banner probes **only** when the user holds the permission the endpoint actually requires, probes silently, and **stops polling** on 403/404. Veri*Factu's own screens keep showing genuine denials for the action the user performed — inline and with a labelled toast.
* `/auth/me` is sent with the selected clinic, and grants are re-read when a stale clinic selection is repaired.
* Cross-permission contamination was removed wherever an *optional* enrichment could shout over another module's screen: copilot metrics/nudges/pending and settings, the agenda note indicator, budget→billing probes, patients→patients_clinical enrichment, the professionals list in cosmetic positions.

No permission was granted or widened, no gate removed, no provider faked, no Veri*Factu surface made public.

---

## 3. What was fixed, by commit

### 3.1 `45f7740` — scope errors to their operation, isolate Verifactu (47 files)

The root-cause fix (§2), plus the surfaces it exposed:

* `utils/permissions` — frontend wildcard matching that mirrors the backend's `permission_matches`, so the probe gate means the same thing on both sides.
* `utils/apiContext` — derives a human operation label from a request path, so a toast can say *what* failed.
* `utils/error` — `errorDetail()` understands the structured `{code, message, missing_or_stale}` details the AI modules emit, not just plain strings and 422 lists.
* dental_3d (scene, card, implant planning, risk engine) — surface the backend's real prerequisite/readiness/provider messages inline instead of a generic string, so a 404 *never generated* is distinguishable from a 409 *missing reference frame*.
* Six Veri*Factu settings pages + `CopilotSettingsPanel` — real `catch` blocks with inline, operation-specific errors and restored button state (they were `try/finally` with no catch: buttons failed silently and rejections went unhandled).
* `useModuleAdmin` — the module list *is* the page, while `/-/status` and `/-/doctor` are diagnostics: they degrade individually instead of blanking the screen through a `Promise.all`.
* `settings/modules` — the no-access panel states the required capability instead of a bare "Access denied".

### 3.2 `b0fb6d6` — ambient loads and polling must report honestly (38 files)

* `useHomeAgenda`: the today/tomorrow loads are silent and set `todayError`/`tomorrowError` instead of flattening a failure into an empty list. "In clinic now" re-polls every 60 s, so a backend blip used to stack one global toast per tick **while the tile claimed nobody was in the clinic**. All four widgets now render an explicit error state with a retry, distinct from a genuine all-clear.
* `AppointmentKanbanView` (30 s poll + tab-focus refresh) and `ProfessionalsStrip` (30 s poll): silent background refreshes, failure rendered inline with a retry — never mistaken for an empty day, and the strip no longer silently vanishes.
* `useAppointments.fetchAppointments` / `useProfessionals.fetchProfessionals` accept `{ silent }`; the appointments error is localized and carries the server's reason instead of a hardcoded string nothing rendered. Cosmetic professional callers (timeline author names, doctor chips, agenda lanes) pass `silent` — they fall back to the record's own text and own no error surface.
* `migration_import` `DataMigrationPage`: every step (validate, preview, execute, proposals load / bulk-accept / row patch) was a bare `await` in a click handler — the rejection escaped unhandled and the button just stopped doing anything. Each now has a busy flag, an inline localized error and a silent request. The 2 s job-status poll was unguarded **and never stopped on failure** (it threw before reaching its stop condition, so it re-fired forever); it now reports inline, stops, and offers a retry.
* `prescriptions` page: patient search was an unguarded `await` in an `@input` handler; loading the history had no error state, so a failure rendered as "no prescriptions"; the per-prescription delivery audit used `Promise.all`, so one failed history rejected the whole refresh.

### 3.3 `40c767c` — translate every raw key, report each failure exactly once (25 files)

* **47 keys** that rendered as raw identifiers or fell back to English were added to all five host locales (the legal-guardian form, every `errors.*` toast title, invoice status/messages, `actions.back`/`change`, `common.*` labels, attachment/document/photo-gallery messages), plus `notifications.smtp.*` for es/fr/pt and the odontogram treatment categories for es. **2589 static keys** now resolve in en/es/fr/pt/ar.
* An unescaped `@` in an email placeholder broke the whole locale file: `@` is vue-i18n's linked-message operator, so the message compiler rejected the file and **every `t()` in that language silently rendered raw keys**. Escaped as `{'@'}`.
* New `tests/i18n/keys.test.ts` (8 tests) scans host + module layers for static keys, asserts each resolves in all five locales, asserts no message can break compilation, and pins the fixed keys.
* **One failure, one report**: composables that compose their own toast now pass `{ silent: true }` — treatment plans (21 calls), notification settings and sending (9), users (3), budget settings, odontogram tooth updates, medical history. Where the local toast carried no reason it now carries the server's (`errorDetail`/`errorMessage`), so silencing the shared layer never loses information.

### 3.4 `6025974` — clinic scoping, real confirm dialogs, no silent dead-ends (52 files)

* **Thirteen requests that cannot go through `useApi`** — blob/array-buffer downloads (invoice & budget PDFs, documents, photos, note thumbnails, dental meshes & DICOM), the accounting export, the recalls CSV and the **copilot SSE stream** — sent `Authorization` alone. Without `X-Clinic-Id` the backend falls back to the alphabetically-first membership, so a multi-clinic user resolved another clinic's role: permission checks ran against grants they are not using and per-clinic documents came back on the wrong letterhead. All thirteen now use a shared `useApiHeaders` helper; a scan confirms **no call site builds auth headers by hand** any more (only `useApi`, `useAuth`'s refresh and the helper contain a Bearer template). `tests/composables/apiHeaders.test.ts` (4) pins it, including following a clinic switch and never inventing one.
* **`window.confirm` is blocked inside an iframe**, so every destructive action behind it silently returned early — a Delete button that does nothing. Replaced by a real `confirmDialog` composable + host component (`tests/composables/confirmDialog.test.ts`, 3 tests: resolves true/false, and a superseded request settles so no caller hangs).
* Accounting-export preview/download and the recalls CSV export were `try/finally` with no catch (the download bypasses `useApi` entirely): a failure was a spinner that stopped. Both now report — the preview inline (silent at the API layer so a 422 on a bad range is not lost), the download with the server's own reason.
* Budget expiry / public-link / reminders and clinic-language settings: same class, same fix.
* `useConversation.fetchThread` renders an inline error + Retry instead of "no messages yet"; `reply` is caught by its caller.

### 3.5 `64e6d40` — the public budget link must tell the patient (3 files)

`/p/budget/<token>` talks to the public endpoints with raw `$fetch`, so there was no shared toast and no error shaping; both loaders were `try/finally` with no catch, so a failure rejected out of `onMounted` and left `meta` null — which the template renders as loading skeletons. **Forever.** A patient clicking a valid link during a network blip, or after the token was purged, expired or locked, could not tell "still loading" from "call the clinic".

`usePublicBudget` now exposes `loadError` (`not_found` | `expired` | `locked` | `generic`) mapped from the status and never rejects; the page renders a card — icon, reason, Retry — ahead of the skeleton branch. No new translation keys: every case reuses copy the page already ships in five languages. `tests/composables/publicBudgetLoad.test.ts` (5 tests) covers 404/410/423/network mapping, a body failure after good meta, and the error clearing on a successful retry.

### 3.6 `7960143` — report a failed action where it happened, not as missing data (11 files)

The last `try/finally`-without-`catch` sites wrapping a **direct** API call. Four turned a failure into a *claim*:

| Surface | What a failure looked like | Now |
|---|---|---|
| WhatsApp (Kapso) settings | A form built from blanks **with a live Save** — one click from overwriting the clinic's stored phone number and secrets with empty strings | `fetchSettings` exposes `error`; the page renders it with a Retry **instead of the form** |
| Appointment notes panel | "no notes for this appointment" — a clinical claim nobody established | Reason + Retry |
| Treatment-notes popover | "no notes yet"; worse, the failure escaped `handleSubmit`, so a note that **saved** but whose refresh failed looked like a failed save and left the composer open with the body in it — a duplicate-note trap | `refreshFull` no longer rejects; the read failure is reported inline |
| Expanded invoice row | "No payments" — `fetchPayments` caught and returned `[]`, making a denial indistinguishable from an invoice with no payments | It rejects; the row reports the failure with a Retry |

Closing or discarding a periodontogram session was the quiet one: a 409 (already closed) or a 422 dismissed the dialog, left the draft untouched and told the clinician nothing. Both now route the server's reason to `lastError` — which the chart already turns into the single save-failed toast — and **still reject**, so no caller can mistake it for a closed or discarded session. `useClinicalNotes.listForOwner` gained an optional `{ silent }`; both panels render the failure inline instead of an empty state. The periodontogram autosave toast carried `e.message` (`"409 Conflict"`); it now carries the server's reason.

### 3.7 `ef76ede` — a report that cannot be read is not a clinic with nothing to report (20 files)

Every fetcher in `useReports` / `useHomeReports` caught its failure, logged it and resolved to `null`/`[]`. The pages then rendered the *absence* of data as fact: zeroed KPIs, "No data" cards, a silently missing invoice-numbering-gap alert, and — worst — a green **"No overdue invoices"** all-clear on both the billing report and the home dashboard. A receptionist without `reports.billing.read` saw a clinic that owed nobody anything.

* The composables keep an **error ledger keyed by section** and expose `errorSummary`; fetchers are silent so one denial is reported once, by the surface that owns it.
* The billing / budgets / scheduling report pages render a `UAlert` + Retry above their sections instead of empty cards, and each section reports its own failure inline rather than as "no rows".
* The dashboard tiles (KPI, cash collected, production, aging receivables, funnel, payment methods, advances, new patients) render the failure in place — including the per-card `error` flag `useDashboardSnapshot` already tracked but **no component ever displayed**.
* `tests/reports/failureStates.test.ts` (9 tests) pins all of it.

### 3.8 `085d0f4` — give jsdom its own undici 7 so the copilot bundle can load (2 files)

`overrides.undici = "8.10.0"` (a security pin) applied to the whole tree including jsdom 29 — which `isomorphic-dompurify` pulls in to sanitise on the server, and which requires `undici@^7.25.0`. undici 8 removed `lib/handler/wrap-handler.js`, so loading the package threw `Cannot find module 'undici/lib/handler/wrap-handler.js'`.

**This is not only a test problem.** Nitro externalises `isomorphic-dompurify` into `.output/server/node_modules`, and the built tree reproduced the same crash on import: server-rendering `/copilot` (page → `CopilotDrawer` → `CopilotMarkdown`) threw during module load instead of returning a page. Any first paint, crawler or non-JS client hit it. A **nested** override gives jsdom undici 7 and leaves the app-wide 8.10.0 pin untouched; the lockfile change is exactly one added package. Verified by importing from the built `.output/server` tree.

### 3.9 `20c3199` — a null collection payload is an empty list (33 files, 38 sites)

38 list refs were fed straight from the response envelope (`items.value = res.data`). Every one is declared `Something[]`, so a payload of `{"data": null}` — an empty collection serialised as null by the API, a cache or any layer between — put `null` into an array ref, and the next render threw inside the template (`v-if="nudges.length"`, `v-for`, `.map`), taking the whole component subtree down instead of showing the empty state it already has. **Reproduced, not hypothesised**: mounting the Copilot drawer against a null nudges payload crashed in `CopilotNudges.vue`. Each assignment now normalises with `?? []`.

### 3.10 `1601c7e` — stub nprogress once for the suite (3 files, test infra)

The client NProgress plugin removes its bar from a nested ~200 ms timer. Under vitest that timer outlives the environment of the file that started it and the callback dies with `ReferenceError: document is not defined`; vitest counts that as an unhandled error and fails the whole run **even though every test passed**. Because the timer fires inside whichever file happens to be running, stubbing per file only moved the failure around. A single setup file now mocks it for every test file. (Aliasing the module in `vitest.config` is not an option: an array `resolve.alias` there replaces the object form Nuxt injects and loses `#app`, failing all 42 files.)

### 3.11 `d51023e` — the last uncaught rejections (11 files)

Five surfaces still had API calls with **no `catch` anywhere on the path**, so the rejection escaped a click handler or an immediate watcher while the UI showed its empty state:

* **Copilot**: the composer cleared the clinician's message *before* sending, so a failed session create **destroyed what they had typed**. The input is cleared only once the send settles successfully, and a picked nudge/pending prompt is restored to the draft when its send fails.
* **Clinic hours / professional schedules**: both pages rendered the weekly grid from empty defaults, **with a live Save**, when the load failed — one click from overwriting the clinic's real opening hours. Loaders are silent now; the pages render a `UAlert` + Retry in place of the grid; both `confirmDelete` paths report their own failure with the detail.
* **Clinical notes**: `listMergedForPlan`, `listGroupedForPatient` and `listTemplates` caught and resolved to `[]`, so the plan timeline and the patient notes tab rendered "no clinical notes". The composable exposes `error`; both panels render it inline.
* `tests/composables/uncaughtActionFailures.test.ts` (9 tests) pins each, including that a failed Copilot send **keeps the typed message**.

### 3.12 `eaa6330` — a late response must not overwrite the record the user moved to (23 files)

Every list and record is re-fetched by a watcher on whatever the user just changed — patient, plan, appointment, day, filter chip, search box, pagination — and none checked whether it was still the newest. **Debouncing does not prevent this; it only makes it rarer.** The worst cases were clinical:

* the odontogram chart, its treatment list and its history timeline re-fetch on `watch(() => props.patientId)` — a slow answer for patient A rendered **A's teeth under patient B's name**;
* `fetchOdontogramAtDate` also wrote `viewingDate` from the late response, so clicking through history dates quickly could show one date's chart under another date's label;
* the medical history (allergies, anticoagulants) and the patient alert banners follow the same watcher — the wrong warnings raised, or the right ones hidden.

The fix is a small utility, `frontend/app/utils/latestGuard.ts`: `const isLatest = guard.begin()` at the start, `if (!isLatest()) return` before writing data or error, `if (isLatest())` before clearing a loading flag, and `guard.invalidate()` on state-clear paths. For lists that live in `useState` and are read by several components at once there is `useSharedLatestGuard(key)` — a module-scope counter would be wrong under SSR, so the counter lives in `useState` (keys: `appointments:list`, `budgets:list`, `catalog:items`, `invoices:list`, `agenda.home:today`, `agenda.home:tomorrow`, `catalog:vat-types`). `tests/utils/latestGuard.test.ts` (6 tests) covers the utility itself, including four overlapping rounds and one shared counter per key. 21 module files were guarded in this commit.

### 3.13 `8dbbda6` — pickers and viewers must show what the user last asked for (7 files)

| Surface | Trigger | What a stale response did |
|---|---|---|
| `PatientSearch` | a search on focus **and** 300 ms after every keystroke | Listed patients that do not match the box — the next click **selects one of them** |
| `useTreatmentCatalogSearch.search` | typing in the treatment picker inside the appointment / budget / plan modals | Offered treatments that do not match the query, one click from being added to a plan |
| `FilterEntityPicker` | debounced typing + `onOpen()` | Same race, **plus** a `try/finally` with no catch: the rejection escaped the debounce timer and the popover rendered *"no results"*. Now reports inline with Retry |
| `PlannedTreatmentSelector` | selected patient changes | Offered the previous patient's pending treatments |
| `PatientBillingSummary` | page click **and** patient switch | Replaced the page/patient now on screen |
| `PhotoLightbox.loadCurrent` | arrow-key navigation through clinical photos | Displayed a late blob under the current photo's caption — and the preceding `revokeObjectURL` could free the URL now on screen. Superseded blobs are revoked instead |

`tests/composables/staleResponseRaces.test.ts` (4 tests) parks the requests and answers them **newest first, stale last**, then asserts what is on screen. Verified as real regression tests: neutralising the guards in the patient timeline and the notes tab fails two of them with `expected [ 'entry-a' ] to deeply equal [ 'entry-b' ]` and with patient A's plan rendered on patient B's tab.

### 3.14 `2aaff85` — the rest of the stale-response sweep, and a billing denial that read as "no invoices" (12 files + 1 test)

§3.12/§3.13 covered the composables behind patient-, plan- and picker-driven fetches. These fetch from a **page or component** instead, so they were invisible to that pass:

| Surface | Trigger | What a late answer did |
|---|---|---|
| `reports/billing.vue`, `reports/budgets.vue`, `reports/scheduling.vue` | date-range change re-reads every section | The previous range's slow answer replaced the numbers on screen — a **report that reads as fact** |
| `payments/reports/index.vue` | range + professional + status filters | Same, on three separately-fetched sections; the busy flags were also left set on the failure path, so a failed filter change could strand the panel in its spinner |
| `useHomeAgenda` | the 30 s poll **and** a manual refresh | A poll answered after a refresh could paint older today/tomorrow tiles over the newer ones |
| `AppointmentDailyView.refreshAvailability` | day switch (two awaits in one handler) | The previous day's availability rendered under the selected day — one click from booking into it |
| `ProfessionalsStrip` | professional/cabinet filter change | Listed the previous filter's professionals; a `null` payload also crashed the render |
| `recalls/index.vue` | status + due-date filters | The filtered list could show the previous filter's recalls |
| `invoice-series/index.vue` | the `showInactive` toggle | An inactive-inclusive answer could land after the user switched back |
| `useVatTypes` | the `showInactive` toggle | Same, behind a shared `useState` list — so it takes `useSharedLatestGuard('catalog:vat-types')` |
| `useClinic.fetchClinic` | clinic switch | A `null` clinic payload was dereferenced directly |

**Also in this commit, and not a race:** `PatientBillingSummary.loadInvoices` caught every failure and emptied the list, so a *denied* invoices read rendered as **"this patient has no invoices"**. It now keeps an `invoicesError`, calls the API `{ silent: true }`, and renders an inline reason with a Retry that reloads just that panel. `tests/billing/patientInvoicesFailure.test.ts` (2 tests) pins both halves: the denial shows the error + Retry and **no** table and **no** global *Access Denied* toast; after a successful Retry the alert is gone and the invoice number renders. Verified to fail with the fix reverted.

### 3.15 `faca30e` — a second click on a pending write must not write twice (4 files + 1 test)

| Surface | Second click while the first was in flight |
|---|---|
| `ClinicHoursPage.saveOverride` / `ProfessionalSchedulesPage.saveOverride` | **Created a second override for the same dates** — two contradictory closed-day entries for the clinic, nothing on screen to say why. Now a busy flag plus `:loading` on Save. Their failure toast also carried `err.data?.message ?? ''`, i.e. an empty description whenever the server sent none; it now carries `errorDetail(err)` |
| `OdontogramChart` treatment update / delete / perform | A second Delete sent a second DELETE whose **404 was toasted as a failure after the success toast**; a second Perform repeated the completion. One flag covers the three |
| `DocumentGallery.confirmDelete` | Same duplicate DELETE — and it closed the dialog even when `deleteDocument` returned `false`, which **reads as a successful delete of a document that is still there**. It now stays open on failure, and Confirm shows its pending state |

`tests/schedules/doubleSubmit.test.ts` parks the create request, clicks Save three times and asserts exactly one POST reached the network. With the fix reverted (committed file + the test hook only) it fails with `expected [ …(3) ] to have a length of 1 but got 3` — three duplicate overrides. The nuance it exposed: `:loading` alone already blocks the clicks (Nuxt UI disables a loading button), so the handler-level guard is what holds for a click that lands **between renders**.

The scan that found these (write-handler buttons with no `:loading`/`:disabled`/busy early-return: **50 candidates, 12 reaching a write**) also cleared the rest: destructive actions behind `confirmDialog` (invoices, budgets, treatment plans, plan notes, overrides) cannot be double-clicked, because the dialog resolves once and closes; `RecallRow.bookAppointment` only navigates; the recall snooze/cancel buttons already carry a busy flag.

### 3.16 `0b2a663` — the last column of the sweep (1 file)

`useProfessionals.fetchProfessionals` guarded the payload on the way into the list (`response.data ?? []`) and then dereferenced **the same payload unguarded** on the next line to build the colour map, so a `null` list threw a `TypeError` inside the `try` — surfaced as a professionals *load* failure while the list had in fact loaded.

This closed the audit of `await`-then-assign sites in `frontend/app` (13 candidates). The rest are documented rather than guarded for show: `useAuth`'s token/permission writes are single-flight per session boot — `init()` only calls `fetchUser()` while `accessToken && !user`, and the clinic switcher cannot render before that resolves (it needs `clinics`) — and `switchClinic` applies token, user, permissions and selection from **one** landing response before reloading the page. `useModules`, `useClinic.fetchClinic` and `useProfessionals` re-fetch the same resource with no parameters, so overlapping calls write identical data. `useUsers`'s three writes are serialised twice over: each `create/update/delete` awaits its own `fetchUsers()` before returning, and every button already carries `:loading`.

### 3.17 `e95ebd6` — the clinic switcher must behave like a menu (1 file + 1 test)

The switcher is the **only hand-rolled menu in the shell** — every other overlay is a `UModal`, `USlideover` or `UDropdownMenu`, which Nuxt UI dismisses, traps and focuses for us. This one had none of that: no keyboard path at all (Tab reached the trigger and stopped); clicking elsewhere left the panel floating over the header and content until the trigger was clicked again; and `choose()` was not single-flight, so a second pick in the same tick — before Vue re-rendered the closed menu away, which is what a repeated Enter lands as — minted a token for a *different* clinic and raced the page reload that follows.

Now: `aria-haspopup`/`aria-expanded` on the trigger, `role="menu"`/`menuitem` on the panel; opening moves focus to the clinic the trigger already names (so Enter confirms what is on screen); ArrowUp/Down walk the list with wraparound, Home/End jump; Escape and an outside `pointerdown` both close it **and return focus to the trigger**; the switch is single-flight with the trigger disabled and its chevron turning into a spinner.

`tests/layout/clinicSwitcher.test.ts` (5 tests) was negative-checked twice: with the keyboard and pointerdown handlers stubbed out, 3 fail; with only the single-flight guard removed, the double-pick test fails with `expected "vi.fn()" to be called 1 times, but got 2 times`.

The rest of the shell was verified rather than assumed: `PatientSearch` and `VisualSelector` dismiss on blur and select through `@mousedown.prevent` (so a click on a result is not swallowed by the blur that closes the list); `HelpButton`, `FilterBar` and `ModuleDetailModal` are Nuxt UI modal/slideover and inherit Escape and focus trapping; the modules page's `fixed inset-0` overlay is the restart-in-progress blocker, deliberately not dismissible; and the other 9 absolutely-positioned `v-if` panels are drag indicators, a "now" marker, chart cursors and error overlays — nothing that needs dismissal.

### 3.18 `b47dc1c` — the prescriptions patient picker, and invoice rows a keyboard can reach (2 files + 2 tests)

**Prescriptions → patient picker** (a hand-rolled input plus an absolutely positioned result list):

| Defect | Harm | Fix |
|---|---|---|
| One `/api/v1/patients?search=` request per keystroke, nothing checking which answer was newest | A slow reply for a shorter prefix replaced the results for the text in the box — patients that do not match the search, one click from being put on a prescription | `latestGuard()` from §3.12; the superseded answer is dropped |
| The list only vanished when it was *emptied* | It stayed floating over the form after the user clicked away; Escape did nothing | Real open state; Escape and an outside `pointerdown` close it |
| No keyboard path to a result | A result could only be reached with a mouse | ArrowUp/Down + Home/End move an active option, Enter selects it; the input is a `combobox` (`aria-expanded`, `aria-controls`, `aria-activedescendant`) over a `listbox` of `option`s; the label is bound with `for` |

**Patient billing summary → invoice rows.** The whole row is the click target for expanding an invoice and reading its payments, and `cursor-pointer` said so — but a `<tr>` is not focusable, so a keyboard user tabbed straight past the invoices of the patient in front of them. The row is now in the tab order with `aria-expanded`, Enter and Space do what a click does, and it **keeps its table semantics** rather than being re-roled as a button.

Both test files were negative-checked (the picker's four fail with the guard, keydown handler and pointerdown handler stubbed out; the row's two fail with `tabindex`/keydown removed). *Diff note:* `eslint --fix` on the prescriptions page also reflowed ~19 pre-existing single-line elements to one attribute per line — warnings present at HEAD; the file now lints clean and no behaviour in them changed.

### 3.19 `4de533c` — the notification-settings writes must be single-flight (1 file + 1 test)

Every button on that page carries `:loading`, which blocks a second *mouse* click — but that is not the only way back into the handlers. Both dialogs are forms with `@submit.prevent`, so Enter in a field submits them, and any handler can be re-entered in the same tick before Vue renders the disabled state. None of the four operations checked its own busy flag:

| Operation | A second request meant |
|---|---|
| `testEmailConnection` | a second test email to the same address |
| `testSmtpConnection` | a second SMTP test against the provider |
| `updateSmtpSettings` | a second credentials write — the one that can store a **half-applied password**, since the password field is only sent when one was typed |
| `updateSettings` | a second settings PUT and a second success toast |

The guard lives in the composable, not the page, because that is the choke point every consumer passes through and the flags already live there in shared `useState` keys. A superseded call returns `false` and adds no report of its own — the in-flight call owns the single toast — and `finally` releases the flag, so nothing is wedged. `tests/notifications/settingsSingleFlight.test.ts` (5 tests) parks each write, re-enters it and asserts exactly one request, then proves the next call after it settles still goes through; with the guards removed all four double-call tests fail with `expected [ …(2) ] to have a length of 1 but got 2`.

### 3.20 `cd57e2c` — a failure that is swallowed is a control that lies (6 files + 2 tests)

A sweep of **every catch block in the app that surfaces nothing** — 23 of them, triaged one by one — found three that turn a failure into a false statement on screen, and twenty that are genuinely fine (a non-JSON error body being parsed for its detail, an idempotent viewer-tool registration, a thumbnail falling back to its icon placeholder, a decorative cross-module badge whose absence claims nothing, a `useState` called outside a Nuxt context, a locale switch that keeps the current language, a doc comment).

**The odontogram's treatment read** (`useTreatments.fetchTreatments`) caught and only logged, so:

* a denied or missing read rendered as a **clean mouth** — "this patient has had nothing done", a clinical claim nobody established, on the screen a dentist reads before deciding what to do next. The chart's own alert already said *"never fall through to a fabricated healthy mouth"*, but it only watched the tooth-grid read; it now watches this one too, with the reason as its description;
* the list was **not cleared** on failure, so switching from patient A to patient B with B's read failing left **A's treatments painted under B's name**.

It now drops the list and sets an `error`, exposed as `treatmentsError` through `useOdontogram`; `reset()` clears both.

**Two dead clicks.** `CopyableField` (and `DemoCredentialsHint`, same shape) swallowed a clipboard rejection, so the copy button looked like it worked and the user pasted something stale elsewhere — the app already had `common.copyFailed` in all five locales and already used it in `EntityInfoCard`, so this reports the same way. And `SetRecallFromTreatmentButton` caught its treatment lookup with a comment about failing silent "rather than leaving an obviously broken button" — but a button that ignores the clinician *is* the broken button, and the case it feared (a host without the endpoint) is a **404**, precisely the status the shared handler stays quiet about. It now owns the report with `{ silent: true }` plus the server's own reason, and stays clickable to retry.

Tests: `tests/odontogram/treatmentsLoadFailure.test.ts` (4 — the reason is reported, the previous patient's treatments do not survive a failed switch, a retry clears the failure, `reset()` clears it) and `tests/ui/deadClicks.test.ts` (3 — a rejected clipboard reports an error, a successful copy reports success only, a failed recall lookup reports the reason and opens no modal). Both fail with the fixes reverted; the odontogram one fails with `expected [ { id: 'tr-pat-1-1', …(2) }, …(1) ] to deeply equal []`, i.e. patient one's treatments still on screen for patient two.

### 3.21 `4eb5539` — a failed close must not throw away the clinician's notes (2 files + 1 test)

Closing a periodontogram session asks for observations. The dialog closed itself and wiped the textarea **the instant it emitted** — before the request resolved — so when the close failed (a 409 because the session was closed in another tab, a 422, a network drop) the clinician got an accurate toast, the session correctly stayed a draft, and everything they had typed was gone: reopen the dialog, retype it, try again. Discard had the same shape, minus the notes.

This was listed in §6 as a UX follow-up; on re-reading it is the same class as the Copilot composer that destroyed the typed message on a failed send (§3.11) — **user input lost to a failure the user did not cause** — so it is fixed rather than documented.

`PerioIndicesBanner` now keeps the dialog exactly as the clinician left it, and only the parent (`PeriodontogramChart`) closes it, because the parent is what knows the outcome: `handleClose` tracks `closing`, calls the banner's exposed `closeSucceeded()` when `closeSession` actually resolved, and leaves the dialog and its notes untouched otherwise; `handleDiscard` does the same with `discarding` / `discardSucceeded()`. Both confirm buttons show their pending state and both handlers ignore a re-entry while one is in flight — a second click on Close used to emit a second `close` for the same session.

`tests/periodontogram/closeSessionNotes.test.ts` (3 tests) types observations, confirms, and asserts the notes survive a close that did not take; that the dialog closes and clears only on the parent's success call; and that a second click in the same tick does not fire a second close. All three fail with the old emit-then-clear behaviour restored (`expected null to be truthy` — the dialog, and the notes with it, are already gone).

---

## 4. Security posture

| Requirement | Result |
|---|---|
| Do not grant `verifactu.settings.read` | **Not granted.** The probe now checks the permission the endpoint actually requires and skips itself without it — `tests/verifactu/isolation.test.ts` asserts the probe **is not even called** for a role that lacks the grant |
| Do not weaken RBAC / bypass authorization | No permission check removed, widened or inverted. `utils/permissions` now *mirrors* the backend's `permission_matches` wildcard semantics instead of guessing |
| Do not convert 403 → success | Errors are still thrown to the caller. What changed is *who reports* and *whether the report names the operation*. A denied Veri*Factu action on a Veri*Factu screen still shows its denial |
| Do not hide genuine Veri*Factu errors on Veri*Factu pages | Veri*Factu's own screens keep inline errors and labelled toasts; only the **ambient** probe went silent, and it stops polling on 403/404 rather than retrying forever |
| Preserve doctor approval / safety gates | Untouched. The AI readiness and prerequisite messages are now *more* visible (structured `{code, message, missing_or_stale}` details rendered inline), not less |
| No fake providers, no mock data in production paths | None added. Every error state renders the server's own reason; empty states now only mean empty |
| No test deleted to make a suite pass | 0 deleted; 24 → 53 files, 328 tests |
| `main` and PR #65 untouched | `git ls-remote` confirms `main` = `f1c79ca`; no merge, no PR interaction |

---

## 5. Verification — CODE-VERIFIED

| Check | Command | Result |
|---|---|---|
| Type check | `npx nuxt typecheck` (vue-tsc, app + all 27 module layers) | **EXIT 0** |
| Lint | `eslint` on every changed file | **0 errors, 0 warnings** |
| Unit / component tests | `npx vitest run` | **53 files, 328 tests — all pass, 0 unhandled errors** |
| Production build | `npx nuxt build` (Nuxt client + Nitro server) | **EXIT 0**, `✨ Build complete!`, **0 i18n compile errors**; the only `ERROR` lines are the sandbox's font-CDN fetches (no external network) |
| i18n coverage | `tests/i18n/keys.test.ts` | 0 missing / 2589 static keys × 5 locales |
| Built server bundle | `await import('.output/server/node_modules/isomorphic-dompurify/dist/index.mjs')` | **loads** — before `085d0f4` it threw `MODULE_NOT_FOUND: undici/lib/handler/wrap-handler.js`, i.e. `/copilot` could not server-render |
| Static sweeps | stuck-busy flags, dead links (60 targets), empty click handlers, hand-rolled auth headers, `try/finally` without `catch`, uncaught-rejection sites, null-payload assignments, stale-response sites, double-submit write buttons (50 candidates / 12 real writes), hand-rolled overlays and dismissal (11 found), clickable table rows (1), **catch blocks that surface nothing (23)** | see §6 |

**Test growth: 24 → 53 files (+29 new, 0 deleted), 328 tests passing.** The 155 tests I added:

| File | Tests | Pins down |
|---|---|---|
| `verifactu/isolation.test.ts` | 7 | An unrelated Verifactu 403 does not block patient navigation and produces no toast; the caller still gets the real 403; authorized loads work while a probe is denied; **the probe is not even called without the grant** |
| `composables/useApi.errorScope.test.ts` | 11 | Explicit Verifactu denial names the operation *and* the permission; a patients failure never blames another module; caller-supplied labels honoured; 404/409/422 silent; polling cannot stack toasts; 401 refresh keeps the original operation |
| `dental3d/useRiskEngine.test.ts` | 11 | Risk-engine readiness gating and its inline reason |
| `agenda/useHomeAgenda.test.ts` | 8 | Ambient tiles never broadcast a global error; a failed poll renders an error state, not a false all-clear |
| `i18n/keys.test.ts` | 8 | Every static key resolves in all 5 locales; no message can break vue-i18n compilation; previously-raw keys pinned |
| `utils/permissions.test.ts` / `composables/usePermissions.test.ts` | 6 + 4 | Permission-name resolution, module-admin grants, wildcard parity with the backend |
| `utils/apiContext.test.ts` | 5 | Path → operation label mapping |
| `composables/singleErrorReport.test.ts` | 5 | One failure = one report, carrying the server's reason; inline surfaces instead of toasts; failed search ≠ empty result |
| `composables/settingsLoadState.test.ts` | 5 | A failed settings load exposes `error` and never rejects; the mounted page hides the switch and shows Retry |
| `composables/publicBudgetLoad.test.ts` | 5 | Public budget 404/410/423/network mapping, body failure after good meta, error clears on retry |
| `composables/actionFailureSurfaces.test.ts` | 9 | A failed Kapso settings load hides the secrets form and offers Retry; save/sync stay single-reported; a periodontogram close/discard conflict sets the reason **and still rejects**; a failed note read is not "no notes"; `fetchPayments` rejects instead of returning `[]` |
| `composables/apiHeaders.test.ts` | 4 | Requests outside `useApi` carry `Authorization` **and** `X-Clinic-Id`, follow a clinic switch, never invent one |
| `agenda/useAppointments.errorState.test.ts` | 4 | Agenda error scope; a silent background failure sets an inline error |
| `composables/confirmDialog.test.ts` | 3 | The dialog resolves true/false and a superseded request settles so no caller hangs |
| `composables/useAuth.clinicScope.test.ts` | 3 | Clinic header on the session calls |
| `reports/failureStates.test.ts` | 9 | A denied report read renders the reason + Retry, never zeros / "No data" / a green *"no overdue invoices"*; each section reports its own failure; `errorSummary` names what could not be read |
| `composables/uncaughtActionFailures.test.ts` | 9 | A failed Copilot send **keeps the typed message**; a failed clinic-hours load hides the weekly grid and its Save; clinical-notes panels show the reason instead of "no clinical notes"; a periodontogram 409 surfaces and still rejects; a null list payload renders the empty state instead of crashing the render |
| `utils/latestGuard.test.ts` | 6 | The guard keeps only the newest fetch, drops an in-flight one on `invalidate()`, keeps separate slots independent, survives four overlapping rounds, shares one counter per `useState` key |
| `composables/staleResponseRaces.test.ts` | 4 | Newest-first answers: the timeline shows the patient it is on, public booking shows the selected day's slots, a treatment search matches the text in the box, the notes tab renders the current patient's plan — **each verified to fail with the guard removed** |
| `billing/patientInvoicesFailure.test.ts` | 2 | A denied invoices read shows the reason + Retry instead of an empty "no invoices" table — and never a global *Access Denied* toast; Retry after the grant clears the alert and renders the invoice number |
| `schedules/doubleSubmit.test.ts` | 1 | The override Save parked in flight: three clicks produce exactly **one** POST (with the fix reverted, three) |
| `layout/clinicSwitcher.test.ts` | 5 | The clinic menu: opens onto the active clinic, arrow keys walk it, Escape closes and returns focus to the trigger, an outside click closes it, a second pick in the same tick does not mint a second token |
| `prescriptions/patientPicker.test.ts` | 4 | A stale patient search cannot replace the results for the text in the box; arrow keys + Enter select the *highlighted* patient and read that patient's history; Escape and an outside click dismiss the list |
| `billing/invoiceRowKeyboard.test.ts` | 2 | Enter expands an invoice row and fetches its payments, Space collapses it, a click still works, the row keeps its table semantics |
| `notifications/settingsSingleFlight.test.ts` | 5 | Each of the four settings writes re-entered while in flight produces **one** request, and the next call after it settles still goes through |
| `odontogram/treatmentsLoadFailure.test.ts` | 4 | A failed treatment read is reported, does not leave the previous patient's treatments painted, clears on retry, and `reset()` clears it |
| `ui/deadClicks.test.ts` | 3 | A rejected clipboard reports an error (a successful copy reports success only); a failed recall lookup reports the server's reason and opens no modal |
| `periodontogram/closeSessionNotes.test.ts` | 3 | Typed close-session observations survive a close that did not take; the dialog closes and clears only on the parent's success call; a second click in the same tick does not fire a second close |

---

## 6. Audit closure, and what is genuinely left

**The `try/finally`-without-`catch` audit is closed.** A scan found **48** such blocks; triaged by whether the awaited call can actually reject:

* **38 are flag-resets only** — they await a wrapper that catches internally and returns `null`/`[]` (`PaymentCreateModal`, `RefundConfirmModal`, `PlanDetailView`, most clinical-notes components). No unhandled rejection, and the wrapper already reports. Left alone deliberately.
* **10 call the API directly** — all handled:

| Site | Fixed in | Outcome |
|---|---|---|
| `usePublicBudget.fetchMeta` / `fetchBudget` | `64e6d40` | `loadError` state + patient-facing card with Retry |
| `useConversation.fetchThread` | `6025974` | Inline error + Retry instead of "no messages yet" |
| `useConversation.reply` | — (already correct) | Caller catches and reports |
| `useKapso.fetchSettings` | `7960143` | `error` state; page hides the form, shows Retry |
| `useKapso.saveSettings` / `syncTemplates` | `7960143` | `{ silent: true }`; the page's own toast is the single report, with the server's detail |
| `usePeriodontogramSession.closeSession` / `discardDraft` | `7960143` | Reason routed to `lastError` (one toast), still rejects so no false `closed`/`discarded` |
| `useClinicalNotes.listForOwner` | `7960143` | Optional `{ silent }`; both panels render the failure inline instead of an empty state |
| `PatientBillingSummary.toggleInvoice` | `7960143` | `loadPayments` + per-invoice error with Retry, instead of "No payments" |

**Seven sweeps are closed:**

* **Uncaught rejections** (calls with no `catch` anywhere on the path, plus callees that catch-and-return-empty while the consumer renders the absence as a fact): 5 sites in `d51023e` (§3.11), a sixth (`FilterEntityPicker.search`) in `8dbbda6`.
* **Null collection payloads**: 38 sites normalised in `20c3199` (§3.9), plus `useProfessionals`'s colour map in `0b2a663` (§3.16).
* **Stale responses**: patient/plan/appointment/day/filter/search/page-triggered fetchers in `eaa6330` + `8dbbda6` (§3.12, §3.13); report pages, polls, watchers and settings toggles in `2aaff85` (§3.14); the prescriptions picker in `b47dc1c` (§3.18) — **closed**, with every untouched site justified rather than guessed at (§3.16).
* **Double submit**: every button whose handler reaches a `.post/.put/.patch/.delete` — 50 scan candidates, 12 real writes. Four unguarded and fixed in `faca30e` (§3.15); the clinic switcher in `e95ebd6`; the four notification-settings writes in `4de533c` (§3.19). The rest are already serialised (a `confirmDialog` resolves once and closes; `UsersPage`'s writes await their own refresh behind `:loading`) or were false positives (a handler that only navigates, one that only reads).
* **A failure stated as a clinical or financial fact**: 38 null-payload sites, `fetchPayments` returning `[]`, public budgets, `PatientBillingSummary.loadInvoices`, the reports/dashboard all-clears, and the odontogram's clean mouth (`cd57e2c`, §3.20) — **closed**.
* **Keyboard / focus / dismissal**: every overlay in the app is accounted for (§3.17). The one hand-rolled menu and the one hand-rolled typeahead were fixed; everything else is Nuxt UI (which traps focus and handles Escape) or is not a menu at all (drag indicators, a chart cursor, a "now" marker, error overlays, and the deliberately non-dismissible restart blocker). Focus restoration goes back to the invoking control in both fixed surfaces. The one clickable `<tr>` in the app was made keyboard-operable (§3.18).
* **Catch blocks that surface nothing**: all 23 triaged in `cd57e2c` (§3.20) — 3 fixed, 20 justified.

Also closed by scan rather than by fix: **the notifications centre has no surfaces** — there is no bell, inbox or notification list anywhere in the app. The module ships exactly four Vue files: `ConversationThread` (§3.4), `ManualSendButton` (already `isSending` + `:loading`), `ClinicLanguagePage` (below) and the settings page (§3.19). And the **modal-by-modal / table-by-table pass** was done as a pattern scan (overlays and dismissal, clickable rows and keyboard access, every button that reaches a write, every catch that surfaces nothing) rather than a click-through, because a click-through needs a browser; what a browser would still add is in §7.

**What is genuinely left** — none of it a known broken interaction:

* `getPDFPreviewUrl` in `useInvoices`/`useBudgets` is exported but has **no consumer** (dead code). A URL cannot carry the clinic header, so if it is ever used it needs `clinic_id` as a query parameter.
* `frontend/app/components/settings/pages/StubPage.vue` is likewise **dead code**: its own comment claims the settings registry uses it for catalog, vat-types, invoice-series and notifications, but all four pages now exist and nothing imports it (the registry resolves components through `() => import(...)` callables, and no entry references it). Nothing renders it, so no user can reach a "coming soon" panel.
* `PatientVisualSelector`'s duplicate-phone check swallows its failure, so a network blip means "no duplicate warning" rather than "the check could not run". It states nothing false (it never claims *no duplicates exist*), so it is documented rather than changed.
* **`frontend/modules.json` is committed stale, and lists only 20 of the 27 modules that have a frontend layer.** Missing: `verifactu`, `dental_3d`, `periodontogram`, `whatsapp_kapso`, `accounting_export`, `migration_import`, `orthodontic_simulator` — and every path in it is a **CI-container path** (`/module_layers/...`), as is the committed `backend/app/modules/node_modules` symlink. CI regenerates the file (`.github/workflows/ci.yml` → *"Generate modules.json with host paths"*; `python -m app.cli.modules` does the same locally), so pipelines are fine — but a fresh checkout that builds or tests *without* regenerating it silently drops those 7 Nuxt layers: their routes do not exist and their composables are not auto-imported. That produced false reds three times in this session (3 Verifactu isolation tests failing with `ReferenceError: useVerifactu is not defined`; 3 bogus `Cannot find name 'useCatalog'` typecheck errors; and a full-run failure the moment the file was restored from git mid-session). **Recommendation: stop committing this file** (generate it in `postinstall`), or commit a complete, relative-path version. Regenerating it is part of the local ritual here: write all 27 layer paths before every test/typecheck/build, and `git checkout --` it (with `.nuxtrc` and the `node_modules` symlink) before every commit.
* Low-priority surfaces reviewed and left as they are: `ModuleDetailModal` (read-only, Nuxt UI), `ClinicLanguagePage` (its save reports through the shared layer), the settings registry's watchers, `BudgetSignatureCard`, `NoteComposer.listTemplates`, `DocumentViewer.loadDocument`.

---

## 7. LOCAL-RUNTIME-VERIFICATION REQUIRED

These need a browser and a database; neither exists in this sandbox (no Playwright browser install, no postgres/docker/podman). Each is stated as what to do and what must be true.

1. **The reported symptom** — sign in as a dentist and as a receptionist (roles without `verifactu.settings.read`), then click through patients, AI features and settings for several minutes, across at least two 60-second poll intervals. No *"Permission denied: verifactu.settings.read"* and no generic *Access Denied* may appear. In the network tab, `/api/v1/verifactu/health` must **not be requested at all** for those roles.
2. **Veri*Factu pages still tell the truth** — as the same user, open a Veri*Factu screen and perform an action that requires the grant: the denial must appear, naming the operation and the permission, inline on that screen. Nothing about Veri*Factu's own errors may have gone quiet.
3. **Authorized Veri*Factu** — as an admin with the grant, the banner/poll must work as before, and a genuine backend rejection must still surface.
4. **A patients failure never blames another module** — block `GET /api/v1/patients` and click a patient: the toast must name the patient operation, not Verifactu, copilot or anything else.
5. **Multi-clinic scoping** — as a user in ≥2 clinics whose alphabetically-first membership differs from the selected one: reload the app, then download an invoice PDF, a budget PDF, a clinical photo, a document, a note thumbnail, a dental mesh/DICOM, the accounting export, the recalls CSV, and send a copilot message. Every one must carry `X-Clinic-Id` for the **selected** clinic, and per-clinic documents must come back on the right letterhead.
6. **Destructive actions inside an iframe** — with the app embedded in an iframe (preview panes, portals), delete a document, cancel an appointment, remove an invoice item, delete a treatment-plan item: a real in-app dialog must appear and the action must complete. Before `6025974` these were silent no-ops because `window.confirm` is blocked in iframes.
7. **Public budget link** — visit `/p/budget/<token>` with a purged, expired (`410`) and locked (`423`) token, and with the network cut mid-load: each must render its own card with the reason and a working Retry, never an endless skeleton.
8. **WhatsApp (Kapso) settings** — block `/api/v1/whatsapp_kapso/settings` (or use a role without the grant): the page must show the reason + Retry and **no form at all** (the API-key and webhook-secret inputs must be absent). Then Save with a bad phone number id: exactly **one** toast, carrying the server's validation reason. Same for Sync templates, Map and Send test.
9. **Periodontogram session** — with a draft open, type observations and force a conflict on close (close it in another tab first, then close again here): a single save-failed toast **naming the conflict**, the dialog's action must not mark the session closed, and the draft must still be there to retry. **the dialog must stay open with the observations still typed** (before `4eb5539` they were wiped), and a second click on Close must not fire a second request. Same for Discard. Then edit a cell with the network cut: the autosave toast must carry the reason, not just "check your connection".
10. **Copilot page, server-rendered** — this one needs a plain HTTP client, not a browser: `curl -i http://<host>/copilot` (or *view-source:* / JavaScript disabled) must return **200 with HTML**, not a 500. Before `085d0f4` Nitro threw `Cannot find module 'undici/lib/handler/wrap-handler.js'` while loading the route's bundle. Check the server log is clean.
11. **Copilot composer** — type a message, then make session creation fail (a role without `copilot.use`, or block `POST /api/v1/copilot/sessions`): the text **must still be in the composer**. Click a nudge/pending suggestion with the same block: the prompt must come back.
12. **Clinic hours / professional schedules** — deny the read and open *Settings → Clinic hours* and *Professional schedules*: each must show the reason + Retry and **no weekly grid, no Save button** (previously it rendered blank defaults with a live Save). Then delete an override / a schedule entry with the delete denied: exactly one toast, naming the failure.
13. **Clinical notes** — deny the read and open a treatment plan's notes timeline and a patient's *Clinical notes* tab: inline reason + Retry, never *"no clinical notes"*.
14. **Notes & invoice rows** — open an appointment's notes panel with the read denied: inline reason + Retry, never "no notes for this appointment". Open the treatment-notes popover the same way: inline reason + Retry, never "no notes yet"; and a note that saves while the refresh fails must **not** look like a failed save (composer closes, no duplicate). In a patient's billing summary, expand an invoice with the payments read denied: the row must show the failure + Retry, never "No payments".
15. **Reports as a receptionist** — without `reports.billing.read`, open the billing report and the home dashboard: the overdue surfaces must **not** show a green "no overdue invoices", the tiles must show the failure rather than zeros, and each section must report its own failure with a Retry.
16. **Patient billing summary** — open a patient's *Billing* tab with the invoices read denied (or `GET /api/v1/billing/invoices` blocked): the panel must show the reason and a Retry, **no** invoice table, and **no** global *Access Denied* toast anywhere on the page. Grant it (or unblock) and click Retry: the alert is gone and the invoices render.
17. **Odontogram treatments** — open a patient's odontogram with the treatments read denied or missing (`403`/`404` on `/api/v1/odontogram/patients/<id>/treatments`): the chart must show the load-error alert with the reason and a Retry, **never a clean mouth**. Then load patient A (with treatments), switch to patient B while B's read fails: A's treatments must **not** remain painted under B's name.
18. **Migration import** — run a validation that fails, an execute that fails, and cut the network during the 2 s job-status poll: each step must report inline with a busy flag that clears, and the poll must **stop** and offer a retry instead of re-firing forever.
19. **Session recovery** — let the access token expire, click any action: one refresh, the original request retried, no error toast.
20. **Data migration, accounting export, recalls CSV** — trigger each with a bad range or a denied role: the preview must report inline (a 422 range explanation, not a bare status) and the download must toast the server's own reason; no spinner that simply stops.
21. **Stale responses (needs a throttled network, not a fast machine)** — DevTools → Network → *Slow 3G*, then: switch between two patients quickly and watch the odontogram, the medical history and the clinical-notes tab (each must end up showing the patient now selected); on the public booking page click day A then day B (the slots must be B's); in a treatment picker type a short query then a longer one (the list must match the longer text); in the photo lightbox hold the right-arrow key (the image must match the caption).
22. **Reports under a throttled network** — Slow 3G, open the billing report and change the date range twice quickly: every section must end up showing the **second** range. Same on the payments report with its professional and status filters, on the recalls list, and on the home dashboard tiles while the 30 s poll is in flight.
23. **Double submit (throttled network)** — in *Settings → Clinic hours*, add an override and click Save three times while it is pending: the button must show its spinner and the clinic must end up with **one** override for those dates (before `faca30e`: three). Same on *Professional schedules*. In a document gallery, delete a document and make the request fail: the dialog must **stay open** with the reason and the document must still be listed. On the odontogram, click a treatment's Delete twice: exactly one success toast, and no 404 failure toast after it.
24. **Notification settings under re-entry** — press Enter in the test-email dialog twice in a row, and double-click Save on *Slow 3G*: exactly **one** test email must arrive and **one** settings write must land, with a single success toast. Same for the SMTP dialog's Test and Save — a half-typed password must never be written twice.
25. **Clinic switcher (multi-clinic account)** — open the menu with the keyboard alone (Tab to the trigger, Enter), walk the clinics with ArrowUp/Down, press Escape: the menu must close **and focus must land back on the trigger**. Click anywhere else: it must close. Then switch clinics on *Slow 3G* and pick a second clinic while the first is still minting its token: exactly one switch, one reload, and the clinic you end up in must be the one you picked.
26. **Prescriptions patient picker** — on *Slow 3G*, type two characters then a third: the list must match the **full** text, never the shorter prefix. Reach a result with the arrow keys and Enter: the prescription must be for the *highlighted* patient and the history below must be that patient's. Escape and a click outside must both dismiss the list; a mouse click on a result must still select it.
27. **Invoice rows without a mouse** — in a patient's billing summary, Tab to an invoice row: it must take focus with a visible ring, Enter must expand it (and its payments must load), Space must collapse it, and a screen reader must announce the row as expanded/collapsed.
28. **Dead clicks** — with the clipboard blocked (insecure context, or deny the permission), click a patient's copy button: an error toast must appear, and a successful copy must still toast success only. On a host without the odontogram treatment endpoint, click *set recall* on a completed treatment: a toast must name the failure and no modal may open.
29. **i18n in the browser** — switch the UI language through all five locales (en/es/fr/pt/ar) and walk the surfaces above: no raw keys (`errors.loadFailed`-style identifiers) may appear, and in **ar** the layout must remain usable (RTL).
30. **Full test suite on a real checkout** — `npm ci && npx vitest run` must report 53 files / 328 tests with **0 unhandled errors**, and `npx nuxt build` must succeed. Regenerate `frontend/modules.json` first (§6) or seven module layers will be missing and the run will be falsely red.

---

## 8. Session note (transparency)

**The sandbox was restored from a snapshot twice**, and both times the recovery is worth recording because it changes what "verified" means:

1. **Mid-session restore.** `frontend/node_modules` disappeared (reinstalled with `npm ci`, 1197 packages) and the local `.git` was re-cloned at the base commit, dropping three local commits. **No work was lost** — the pushed commits were intact on GitHub (`git ls-remote` confirmed `40c767c`), so history was recovered with `git fetch` + `git reset --soft FETCH_HEAD`, which kept the working tree and left exactly the new changes staged.
2. **Restore during the final phase.** The local branch was again reset to `f1c79ca` while the working tree still held all 20 phases of work, `frontend/node_modules` was empty again, and the workspace root outside the repository was reverted — which **deleted the first copy of this report**. Recovered with `git fetch` + `git reset --mixed FETCH_HEAD` (branch back to `4de533c`, working tree untouched) and `npm ci` (1198 packages, 22 s). The reset proved the tree was byte-identical to the pushed commit: **0 modified files afterwards**. The report was then reconstructed from the commit history and re-verified numbers, and now lives **inside the repository** (`docs/frontend-ui-repair-report.md`) so a workspace reset cannot take it again.

Two consequences worth stating plainly: (a) every claim in §5 was re-run after the second restore, on the recovered tree, at `cd57e2c`; (b) `frontend/modules.json` being committed stale produced three separate false-red runs (§6) — each time the fix was to regenerate all 27 layers, never to change a test.

The branch holds all twenty-one code commits, pushed (`45f7740` … `4eb5539`) plus the documentation commits carrying this file, verified against the remote with `git ls-remote`.

## 9. Not done

* **Browser E2E (Playwright)** — no browser can be installed in this sandbox. §7 is the checklist that replaces it.
* **Any live-backend / database verification** — no postgres, docker or podman. The `/copilot` SSR crash is the one runtime defect proven here without a browser, by importing the built server tree directly in Node.
* **A browser click-through of every dialog, table and popover.** The pattern-level passes are done and itemised in §6 (overlays and dismissal, clickable rows and keyboard access, every button that reaches a write, every catch that surfaces nothing); what remains needs a real browser.
* The three documented follow-ups in §6 (`getPDFPreviewUrl` and `StubPage` dead code, `PatientVisualSelector`'s silent duplicate check) — none is a broken interaction today.
* **No pull request opened.** Work is committed and pushed to `arena/01a091f7-dentora-clinic`; `main` and PR #65 are untouched. Say the word and I'll open one.
