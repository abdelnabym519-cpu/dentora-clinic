import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useApi } from '~/composables/useApi'
import { useAuth } from '~/composables/useAuth'

/**
 * Regression suite for the Nuxt-instance lifecycle violation that surfaced as
 * "Patients connection error".
 *
 * The defect: `useSelectedClinicId()` wraps `useCookie('clinic_id')`. On the
 * server `useCookie` resolves the request event through `useNuxtApp()`, which
 * only works inside a plugin, a Nuxt hook, Nuxt middleware or a Vue setup
 * function. `useApi.$api` and five deferred `useAuth` functions called it at
 * *request* time instead — from watchers, event handlers and promise
 * continuations, i.e. exactly the contexts where the instance is gone. Nuxt
 * then threw
 *
 *   [nuxt] A composable that requires access to the Nuxt instance was called
 *   outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function.
 *
 * before a single byte went on the wire, and the callers' catch blocks
 * re-reported it as a connectivity problem ("Failed to fetch clinic",
 * "useModules: backend fetch failed", "Patients connection error"). Nothing was
 * wrong with the backend, the session or the clinic header.
 *
 * The fix captures one instance during setup and reads its `.value` later.
 * This suite pins that invariant down from the deferred side: the composable
 * is mounted normally, the request-time window is then opened, and *any*
 * `useSelectedClinicId()` call inside that window is a violation — while the
 * outgoing request must still carry the clinic header the captured ref holds.
 */

const CLINIC_ID = '6f1c2d34-5a6b-4c7d-8e9f-0a1b2c3d4e5f'
const ACCESS_TOKEN = 'access-token-under-test'

const { fetchMock, toastSpy, clinicId } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn(),
  clinicId: {
    /** Re-created per test: `logout()` nulls the ref it captured. */
    ref: { value: '' as string | null },
    /** `'setup'` while mounting, `'request-time'` once the window is open. */
    calls: [] as string[],
    armed: false
  }
}))

// Nuxt compiles `$fetch`/`useToast` to auto-imports captured when the
// composables load, so they are mocked through the Nuxt resolver (same
// approach as useApi.errorScope.test.ts and apiHeaders.test.ts).
mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

/**
 * Stands in for the real `useSelectedClinicId`, recording every call and
 * whether it happened during setup or afterwards. It deliberately does *not*
 * throw when armed: the assertion is on the call record, so an ambient app-boot
 * call can never fail a test by escaping as an unhandled rejection.
 */
mockNuxtImport('useSelectedClinicId', () => () => {
  clinicId.calls.push(clinicId.armed ? 'request-time' : 'setup')
  return clinicId.ref
})

async function withApi(): Promise<ReturnType<typeof useApi>> {
  let api!: ReturnType<typeof useApi>
  const Passthrough: Component = defineComponent({
    setup() {
      api = useApi()
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return api
}

async function withAuth(): Promise<ReturnType<typeof useAuth>> {
  let auth!: ReturnType<typeof useAuth>
  const Passthrough: Component = defineComponent({
    setup() {
      auth = useAuth()
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return auth
}

/** `useAuth` reads the session from cookies, which flush on a tick. */
async function setSessionCookies(): Promise<void> {
  const { useCookie } = await import('#app')
  useCookie('access_token').value = ACCESS_TOKEN
  useCookie('refresh_token').value = 'refresh-token-under-test'
  await nextTick()
}

/**
 * Opens the request-time window and returns the calls recorded while it is
 * open, so each test measures only its own await.
 */
async function inRequestWindow(run: () => Promise<unknown>): Promise<string[]> {
  // Let app boot settle first: plugins and clinic watchers call the composable
  // legitimately during their own setup, and those calls must not be counted.
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  const opened = clinicId.calls.length
  clinicId.armed = true
  try {
    await run()
  } finally {
    clinicId.armed = false
  }
  return clinicId.calls.slice(opened)
}

function lastCall(urlPart: string): { url: string, headers: Record<string, string> } {
  const call = fetchMock.mock.calls.find(([url]: [string]) => String(url).includes(urlPart))
  if (!call) throw new Error(`no request matched ${urlPart}`)
  const [, opts] = call as [string, { headers?: Record<string, string> }]
  return { url: String(call[0]), headers: opts?.headers ?? {} }
}

beforeEach(() => {
  clinicId.ref = { value: CLINIC_ID }
  clinicId.calls = []
  clinicId.armed = false
  fetchMock.mockReset()
  toastSpy.mockReset()
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes('/auth/refresh')) {
      return {
        access_token: ACCESS_TOKEN,
        refresh_token: 'refresh-token-under-test',
        user: { id: 'u-1', email: 'dentist@demo.clinic', first_name: 'D', last_name: 'R' }
      }
    }
    if (String(url).includes('/auth/me')) {
      return {
        data: {
          user: { id: 'u-1', email: 'dentist@demo.clinic', first_name: 'D', last_name: 'R' },
          permissions: ['patients.read'],
          clinics: [{ id: CLINIC_ID, name: 'Demo Clinic', role: 'dentist' }]
        }
      }
    }
    return { data: { data: [], total: 0, page: 1, pages: 1, per_page: 20 } }
  })
})

afterEach(async () => {
  clinicId.armed = false
  const { useCookie } = await import('#app')
  useCookie('access_token').value = null
  useCookie('refresh_token').value = null
  await nextTick()
})

describe('deferred calls must not need the Nuxt instance', () => {
  it('useApi.$api sends the clinic header from the setup-captured ref', async () => {
    await setSessionCookies()
    const api = await withApi()

    const violations = await inRequestWindow(() => api.get('/api/v1/patients'))

    expect(violations).toEqual([])
    const { url, headers } = lastCall('/patients')
    expect(url).toContain('/api/v1/patients')
    expect(headers['X-Clinic-Id']).toBe(CLINIC_ID)
    expect(headers.Authorization).toBe(`Bearer ${ACCESS_TOKEN}`)
  })

  it('useAuth.fetchUser sends /auth/me for the captured clinic', async () => {
    await setSessionCookies()
    const auth = await withAuth()

    const violations = await inRequestWindow(() => auth.fetchUser())

    expect(violations).toEqual([])
    expect(lastCall('/auth/me').headers['X-Clinic-Id']).toBe(CLINIC_ID)
    expect(auth.permissions.value).toContain('patients.read')
  })

  it('useAuth.refresh builds /auth/me headers after its own await', async () => {
    await setSessionCookies()
    const auth = await withAuth()

    // The follow-up /auth/me inside refresh() runs after `await $fetch(...)`,
    // the deepest deferred point in the auth flow: on the server the instance
    // is long gone by then.
    let refreshed: boolean | undefined
    const violations = await inRequestWindow(async () => {
      refreshed = await auth.refresh()
    })

    expect(violations).toEqual([])
    expect(refreshed).toBe(true)
    expect(lastCall('/auth/me').headers['X-Clinic-Id']).toBe(CLINIC_ID)
  })
})
