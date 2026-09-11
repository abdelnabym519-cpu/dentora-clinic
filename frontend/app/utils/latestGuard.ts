import { useState } from '#app'

/**
 * Guard for a fetch whose *trigger* can change while the request is still in
 * flight — typing in a search box, clicking pagination or a filter chip,
 * switching patient, plan or date.
 *
 * Without it the earlier, slower response lands last and the UI keeps data that
 * belongs to a state the user already left: the wrong patient's odontogram,
 * page 2 appended under a list that is now showing page 3, results for "jo"
 * under a search box that says "john". Debouncing does not help — it only makes
 * the overlap less likely, not impossible.
 *
 * One guard per state slot. Call `begin()` at the top of the fetcher; the
 * predicate it returns turns false the moment a newer call to the same guard
 * starts, and the superseded call must then leave the state (and the error
 * surface, and the loading flag) to its replacement:
 *
 * ```ts
 * const loadGuard = latestGuard()
 *
 * async function load(page: number) {
 *   const isLatest = loadGuard.begin()
 *   isLoading.value = true
 *   try {
 *     const res = await api.get<ListResponse>(`...?page=${page}`)
 *     if (!isLatest()) return
 *     rows.value = res.data ?? []
 *   } catch (e) {
 *     if (!isLatest()) return
 *     error.value = errorMessage(e, t('errors.loadFailed'))
 *   } finally {
 *     if (isLatest()) isLoading.value = false
 *   }
 * }
 * ```
 *
 * `invalidate()` is for the path that clears the state *without* fetching —
 * the patient id went empty, the dialog closed — where an in-flight response
 * must be dropped just the same.
 *
 * Deliberately not reactive: it is a plain counter, so it costs nothing and
 * behaves identically in a component, a composable or a store.
 */
export interface LatestGuard {
  /** Marks the start of a fetch. The returned predicate is true only for the most recent one. */
  begin(): () => boolean
  /** Drops every in-flight fetch without starting a new one. */
  invalidate(): void
}

export function latestGuard(): LatestGuard {
  let seq = 0

  return {
    begin(): () => boolean {
      const token = ++seq
      return () => token === seq
    },
    invalidate(): void {
      seq++
    }
  }
}

/**
 * The same guard for a list that lives in `useState` — the agenda board,
 * budgets, the catalog, recalls, invoices. There the *state* is shared by every
 * component that reads it, so the counter has to be shared too: a per-instance
 * guard would let two components fetch the same global list and both win.
 *
 * `useState` is per Nuxt request on the server, so concurrent requests cannot
 * see each other's counters.
 */
export function useSharedLatestGuard(key: string): LatestGuard {
  const seq = useState<number>(`${key}:latest-guard`, () => 0)

  return {
    begin(): () => boolean {
      const token = ++seq.value
      return () => token === seq.value
    },
    invalidate(): void {
      seq.value++
    }
  }
}
