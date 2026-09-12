import type { ApiResponse, PaginatedResponse } from '~/types'
import { apiOperationContext } from '~/utils/apiContext'
import { errorDetail, errorPermission } from '~/utils/error'

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

interface UseApiOptions {
  method?: HttpMethod
  // Accept any plain object so callers can pass a typed domain payload
  // (e.g. ``BudgetCreate``) without an ``as unknown as Record<…>`` cast.
  // ``$fetch`` serializes via JSON.stringify, which handles any object.
  body?: object | null
  headers?: Record<string, string>
  skipAuth?: boolean
  // Query-string params appended to the path. Undefined/null values are
  // skipped. Provided because $fetch's own ``query`` was not wired here,
  // so callers that passed ``{ params: … }`` had it silently dropped
  // (e.g. the Veri*Factu queue tabs all rendered the same list).
  query?: Record<string, string | number | boolean | undefined | null>
  // Optional AbortSignal so callers can cancel in-flight requests
  // (debounced lookups, component unmount, etc.).
  signal?: AbortSignal
  /**
   * Suppress the shared error toast for this request. The error is still
   * thrown — only the *global* notification is skipped, so a failure can
   * never be attributed to the screen the user happens to be on.
   *
   * Use it for:
   * - ambient/background probes (compliance banners, polling tiles) whose
   *   failure must not interrupt an unrelated workflow;
   * - optional requests the caller degrades around (``.catch(() => …)``);
   * - any call whose caller renders its own inline, operation-specific
   *   error state (a card, a form, a modal) — double-reporting the same
   *   failure as a toast *and* inline is noise, and the toast is the
   *   less precise of the two.
   */
  silent?: boolean
  /**
   * Label of the operation for the shared error toast. Defaults to a
   * label derived from the request path, so the message always names the
   * failing operation ("Verifactu health") instead of a bare status.
   */
  operation?: string
}

function _withQuery(path: string, query?: UseApiOptions['query']): string {
  if (!query) return path
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) qs.set(k, String(v))
  }
  const s = qs.toString()
  if (!s) return path
  return path.includes('?') ? `${path}&${s}` : `${path}?${s}`
}

/**
 * De-duplicate identical shared error notifications.
 *
 * Ambient probes poll on a timer: without this, one missing permission
 * produces a stack of toasts (one per tick, per mounted component) for a
 * failure the user cannot act on. Client-only on purpose — a module-level
 * Map must not accumulate state across SSR requests.
 */
const TOAST_DEDUPE_MS = 5_000
const recentNotifications = new Map<string, number>()

function shouldNotify(key: string): boolean {
  if (import.meta.server) return true
  const now = Date.now()
  for (const [seen, at] of recentNotifications) {
    if (now - at > TOAST_DEDUPE_MS) recentNotifications.delete(seen)
  }
  const last = recentNotifications.get(key)
  if (last !== undefined && now - last < TOAST_DEDUPE_MS) return false
  recentNotifications.set(key, now)
  return true
}

/** Test hook: drop the de-duplication window between cases. */
export function _resetApiErrorNotifications(): void {
  recentNotifications.clear()
}

export function useApi() {
  const config = useRuntimeConfig()
  const auth = useAuth()
  const { t } = useI18n()
  const toast = useToast()
  /**
   * The clinic selection is captured here, during setup, on purpose.
   *
   * `useSelectedClinicId()` wraps `useCookie()`, which on the server resolves
   * `useRequestEvent()` -> `useNuxtApp()` and therefore needs the Nuxt
   * instance. `$api` runs long after setup — from watch callbacks, timers,
   * event handlers and promise continuations — so calling it per request threw
   * "A composable that requires access to the Nuxt instance was called outside
   * of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function". The
   * callers' own catch blocks then reported it as a *backend* failure
   * ("Failed to fetch clinic", "useModules: backend fetch failed",
   * "Patients connection error") even though the request was never sent.
   *
   * Capturing one instance is also what `useApiHeaders()` already does, and it
   * stops leaking a BroadcastChannel per request (an instance created outside
   * an effect scope never reaches its `onScopeDispose` cleanup).
   */
  const selectedClinicId = useSelectedClinicId()

  // Use different API URL for server (Docker internal) vs client (browser)
  const apiBaseUrl = computed(() =>
    import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
  )

  async function $api<T>(
    path: string,
    options: UseApiOptions = {}
  ): Promise<T> {
    const {
      skipAuth,
      method,
      body,
      headers: optionHeaders,
      signal,
      query,
      silent = false,
      operation
    } = options

    const headers: Record<string, string> = {
      ...(optionHeaders || {})
    }

    // Add auth header if authenticated and not skipping auth
    if (!skipAuth && auth.accessToken.value) {
      headers.Authorization = `Bearer ${auth.accessToken.value}`
    }

    // Multi-clinic: pin every authenticated request to the user's
    // selected clinic via the X-Clinic-Id header. The backend resolves
    // the clinic context + role/permissions from this selection; if the
    // user is not a member it answers 403. A single-clinic self-hosted
    // install has exactly one option, so the header is harmless there.
    if (!skipAuth && selectedClinicId.value) {
      headers['X-Clinic-Id'] = selectedClinicId.value
    }

    const url = _withQuery(path, query)
    const context = apiOperationContext(path)

    /**
     * Report a failure through the shared toast — always naming the
     * operation that actually failed, never the screen the user is on.
     *
     * Statuses the caller is expected to handle itself (404 empty states,
     * 409 conflicts, 422 validation) stay silent here: they are rendered
     * inline by the calling component, which owns the form/row context.
     */
    function report(error: unknown): void {
      if (silent) return

      const status = (error as { statusCode?: number, status?: number }).statusCode
        ?? (error as { statusCode?: number, status?: number }).status
      const label = operation ?? context.label

      if (status === 403) {
        // Name the missing grant when the backend supplied one: "Access
        // denied" alone reads as if the current page were forbidden.
        const denied = errorPermission(error)
        const detail = errorDetail(error)
        const reason = denied
          ? t('common.forbiddenPermission', { permission: denied })
          : detail ?? ''
        if (!shouldNotify(`forbidden:${context.key}:${denied ?? detail ?? ''}`)) return
        toast.add({
          title: t('common.forbidden'),
          description: reason ? `${label} — ${reason}` : label,
          color: 'error'
        })
        return
      }

      if (status !== undefined && status >= 500) {
        if (!shouldNotify(`server:${context.key}`)) return
        toast.add({
          title: t('common.error'),
          description: `${label} — ${errorDetail(error) ?? t('common.serverError')}`,
          color: 'error'
        })
        return
      }

      // No status at all: the request never reached the server.
      if (status === undefined) {
        if (!shouldNotify(`network:${context.key}`)) return
        toast.add({
          title: t('common.error'),
          description: `${label} — ${t('common.networkError')}`,
          color: 'error'
        })
      }
    }

    const send = (): Promise<T> => $fetch<T>(url, {
      baseURL: apiBaseUrl.value,
      timeout: 10000, // 10 seconds
      method,
      body,
      headers,
      signal
    })

    try {
      return await send()
    } catch (error: unknown) {
      const fetchError = error as { name?: string, statusCode?: number, status?: number }
      const status = fetchError.statusCode ?? fetchError.status

      // Caller-initiated cancellation: don't toast, just rethrow so the
      // caller can no-op. AbortController is used by orchestrators
      // (e.g. dashboard) to cancel stale parallel fetches. A cancelled
      // request is not an authorization failure and must never become one.
      if (fetchError.name === 'AbortError' || signal?.aborted) {
        throw error
      }

      // Handle specific error codes
      if (status === 401) {
        // Try to refresh token
        const refreshed = await auth.refresh()
        if (refreshed) {
          // Retry the request with new token
          headers.Authorization = `Bearer ${auth.accessToken.value}`
          try {
            return await send()
          } catch (retryError: unknown) {
            report(retryError)
            throw retryError
          }
        }
        // Redirect to login
        await auth.logout()
        throw error
      }

      report(error)
      throw error
    }
  }

  // Convenience methods
  async function get<T>(path: string, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'GET' })
  }

  async function post<T>(path: string, body?: object | null, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'POST', body })
  }

  async function put<T>(path: string, body?: object | null, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'PUT', body })
  }

  async function patch<T>(path: string, body?: object | null, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'PATCH', body })
  }

  async function del<T>(path: string, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'DELETE' })
  }

  return {
    $api,
    get,
    post,
    put,
    patch,
    del
  }
}

// Type helpers for API responses
export type { ApiResponse, PaginatedResponse }
