import { ref, defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { _resetApiErrorNotifications } from '~/composables/useApi'

/**
 * The two messages a broken Nuxt context produced in production:
 *
 *   ERROR  Failed to fetch clinic: "A composable that requires access to the
 *          Nuxt instance was called outside of a plugin, Nuxt hook, Nuxt
 *          middleware, or Vue setup function."
 *   WARN   useModules: backend fetch failed — <same message>
 *
 * Neither was a backend failure. `useApi`'s `$api` used to call
 * `useSelectedClinicId()` — a `useCookie()` wrapper, which on the server goes
 * through `useRequestEvent()` -> `useNuxtApp()` — on *every request*, and `$api`
 * is invoked from watchers, timers and promise continuations. unctx restores the
 * instance only for the bodies it transforms (`defineNuxtRouteMiddleware`,
 * `defineNuxtPlugin`, `setup`); an ordinary async function resuming after an
 * `await` runs with no instance, so the acquisition threw before the request was
 * ever sent. `fetchClinic`'s and `ensureLoaded`'s own `catch` blocks then
 * reported that context violation as a connectivity problem, and the Patients
 * screen rendered "Patients connection error" against a healthy backend.
 *
 * These tests reproduce the suspended-instance condition and assert that the
 * real request goes out with the right clinic header, that neither message is
 * logged, and — equally important — that a genuine backend failure is still
 * reported and still leaves the state empty instead of a fabricated clinic.
 */

const CLINIC_ID = '6f1c2d34-5a6b-4c7d-8e9f-0a1b2c3d4e5f'
const E1001 = '[nuxt] A composable that requires access to the Nuxt instance was called outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function.'

const { fetchMock, ctx } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  ctx: { suspended: false }
}))

/** Stands in for unctx clearing the stored instance once the render suspends. */
function acquireNuxtInstance(api: string): void {
  if (ctx.suspended) throw new Error(`${E1001} (${api})`)
}

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useCookie', () => (_key: string) => {
  acquireNuxtInstance('useCookie')
  return ref(CLINIC_ID)
})
mockNuxtImport('useAuth', () => () => ({
  isAuthenticated: ref(true),
  accessToken: ref('stub-token'),
  user: ref({ id: 'u-1', email: 'dentist@demo.clinic', first_name: 'Demo', last_name: 'Dentist' }),
  permissions: ref(['*']),
  init: vi.fn()
}))

/** ofetch-shaped failure: status + parsed body under `.data`. */
function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(typeof detail === 'string' ? detail : 'request failed'), {
    statusCode: status,
    status,
    data: { detail }
  })
}

const CLINIC_PAGE = {
  data: [{ id: CLINIC_ID, name: 'Demo Clinic' }],
  total: 1,
  page: 1,
  pages: 1,
  per_page: 20
}

function headersOf(callIndex = 0): Record<string, string> {
  const call = fetchMock.mock.calls[callIndex]
  return ((call?.[1] as { headers?: Record<string, string> } | undefined)?.headers ?? {})
}

function pathOf(callIndex = 0): string {
  return String(fetchMock.mock.calls[callIndex]?.[0] ?? '')
}

describe('deferred clinic/module fetches under a suspended Nuxt instance', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>
  let warnSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    ctx.suspended = false
    fetchMock.mockReset()
    // `useState` survives across tests in one environment: reset the shared
    // clinic/module state so each case starts from the same place.
    useState<{ id: string, name: string } | null>('clinic:current').value = null
    useState<unknown>('modules:active').value = null
    useState<number>('modules:active:at').value = 0
    useState<string | null>('modules:active:error').value = null
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    errorSpy.mockRestore()
    warnSpy.mockRestore()
    ctx.suspended = false
    _resetApiErrorNotifications()
  })

  it('sends GET /auth/clinics and does not log "Failed to fetch clinic"', async () => {
    const { useClinic } = await import('~/composables/useClinic')

    // Constructed while the instance is available, as a component setup would.
    // `useClinic` registers an immediate watcher, so let that first fetch land
    // before isolating the deferred call below.
    fetchMock.mockResolvedValue(CLINIC_PAGE)
    const clinic = useClinic()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(errorSpy).not.toHaveBeenCalled()

    // The render has since suspended; this is a deferred continuation, which is
    // where the old per-request `useSelectedClinicId()` threw.
    ctx.suspended = true
    fetchMock.mockClear()

    await clinic.fetchClinic()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(pathOf()).toBe('/api/v1/auth/clinics')
    expect(headersOf()['X-Clinic-Id']).toBe(CLINIC_ID)
    expect(headersOf().Authorization).toBe('Bearer stub-token')

    // Real data reached the state — nothing faked, nothing swallowed.
    expect(clinic.currentClinic.value?.name).toBe('Demo Clinic')

    const failureLog = errorSpy.mock.calls.find(c => String(c[0]).includes('Failed to fetch clinic'))
    expect(failureLog).toBeUndefined()
  })

  it('sends GET /modules/-/active and does not log "useModules: backend fetch failed"', async () => {
    // `useModules()` uses component-scoped APIs, so it must be acquired inside
    // setup — which is also the production shape: the layout acquires it in
    // setup and calls `ensureLoaded()` later, on route changes.
    const holder: {
      ensure?: (force?: boolean) => Promise<void>
      modules?: { value: { name: string }[] }
    } = {}

    const probe = defineComponent({
      setup() {
        const modules = useModules()
        holder.ensure = modules.ensureLoaded
        holder.modules = modules.modules
        return () => h('div')
      }
    })

    const wrapper = await mountSuspended(probe)
    expect(holder.ensure).toBeTypeOf('function')

    ctx.suspended = true
    fetchMock.mockClear()
    fetchMock.mockResolvedValueOnce({ data: [{ name: 'ai_case_summary', navigation: [] }] })

    await holder.ensure?.(true)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(pathOf()).toBe('/api/v1/modules/-/active')
    expect(headersOf()['X-Clinic-Id']).toBe(CLINIC_ID)

    // The module list really came back through the composable's own computed.
    expect(holder.modules?.value[0]?.name).toBe('ai_case_summary')
    expect(wrapper.exists()).toBe(true)

    const failureLog = warnSpy.mock.calls.find(c => String(c[0]).includes('useModules: backend fetch failed'))
    expect(failureLog).toBeUndefined()
  })

  it('still reports a genuine backend failure — error handling is not weakened', async () => {
    const { useClinic } = await import('~/composables/useClinic')

    // Construction: authenticated but no clinics yet, so the immediate watcher
    // neither logs nor populates state.
    fetchMock.mockResolvedValue({ data: [], total: 0, page: 1, pages: 1, per_page: 20 })
    const clinic = useClinic()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(errorSpy).not.toHaveBeenCalled()

    // Now the backend genuinely fails.
    fetchMock.mockClear()
    fetchMock.mockRejectedValueOnce(httpError(503, 'backend unavailable'))

    await clinic.fetchClinic()

    const failureLog = errorSpy.mock.calls.find(c => String(c[0]).includes('Failed to fetch clinic'))
    expect(failureLog).toBeDefined()
    expect(String(failureLog?.[1])).toContain('backend unavailable')
    // The failure was NOT converted into a fabricated clinic.
    expect(clinic.currentClinic.value).toBeNull()
  })
})
