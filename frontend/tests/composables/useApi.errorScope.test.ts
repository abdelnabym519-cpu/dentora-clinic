import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useApi, _resetApiErrorNotifications } from '~/composables/useApi'

/**
 * Regression suite for the shared API error layer.
 *
 * The reported defect: clicking around ordinary screens (patients, AI
 * cards) produced "Access denied" / "Permission denied:
 * verifactu.settings.read" because an ambient Veri*Factu compliance probe
 * was denied and the shared handler turned *every* 403 into one global,
 * context-free toast.
 *
 * Contract under test:
 *   - a failure is always reported as the operation that actually failed;
 *   - ambient/optional probes can opt out of the shared report entirely;
 *   - opting out never hides an explicit user action's denial;
 *   - caller-owned statuses and cancellations are never re-reported.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

// Nuxt compiles `$fetch`/`useToast` to auto-imports captured when useApi
// loads, so they are mocked through the Nuxt resolver (same approach as
// the dental_3d composable suites).
mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const RECORD_ID = '3f2b8c1e-6d4a-4b7e-9c2f-1a5d8e7b4c60'

/** Shaped like ofetch's FetchError: status + parsed body under `.data`. */
function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(typeof detail === 'string' ? detail : 'request failed'), {
    statusCode: status,
    status,
    data: { detail }
  })
}

function denied(permission: string) {
  // Exactly what the backend's require_dependency answers with.
  return httpError(403, `Permission denied: ${permission}`)
}

interface ToastCall {
  title: string
  description?: string
  color: string
}

function toasts(): ToastCall[] {
  return toastSpy.mock.calls.map(call => call[0] as ToastCall)
}

/** Run `useApi` inside a component so the Nuxt/i18n context exists. */
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

beforeEach(() => {
  _resetApiErrorNotifications()
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('useApi — ambient probes cannot speak for the current screen', () => {
  it('reports nothing when a background Veri*Factu health probe is denied', async () => {
    const api = await withApi()
    fetchMock.mockRejectedValue(denied('verifactu.settings.read'))

    await expect(
      api.get('/api/v1/verifactu/health', { silent: true })
    ).rejects.toMatchObject({ statusCode: 403 })

    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('still hands the caller the real, unmodified failure', async () => {
    const api = await withApi()
    fetchMock.mockRejectedValue(denied('verifactu.settings.read'))

    const error = await api
      .get('/api/v1/verifactu/health', { silent: true })
      .catch((e: unknown) => e)

    // Context must survive the interceptor: a Veri*Factu health 403 stays
    // a Veri*Factu health 403 for whoever caught it.
    expect(error).toMatchObject({ statusCode: 403 })
    expect((error as { data: { detail: string } }).data.detail)
      .toBe('Permission denied: verifactu.settings.read')
  })

  it('lets an authorized patient load succeed while an unrelated probe is denied', async () => {
    const api = await withApi()
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('/verifactu/')) throw denied('verifactu.settings.read')
      return { data: [{ id: RECORD_ID, first_name: 'Ana' }] }
    })

    // The banner's probe fails in the background…
    await expect(
      api.get('/api/v1/verifactu/health', { silent: true })
    ).rejects.toMatchObject({ statusCode: 403 })

    // …and the patient navigation the user actually performed still works.
    const patients = await api.get<{ data: unknown[] }>('/api/v1/patients')
    expect(patients.data).toHaveLength(1)
    expect(toastSpy).not.toHaveBeenCalled()
  })
})

describe('useApi — an explicit denial is reported accurately', () => {
  it('names the Veri*Factu action and the missing permission', async () => {
    const api = await withApi()
    fetchMock.mockRejectedValue(denied('verifactu.queue.manage'))

    await expect(
      api.post(`/api/v1/verifactu/queue/${RECORD_ID}/retry`)
    ).rejects.toMatchObject({ statusCode: 403 })

    expect(toasts()).toHaveLength(1)
    const [toast] = toasts()
    expect(toast.color).toBe('error')
    expect(toast.description).toContain('Verifactu')
    expect(toast.description).toContain('verifactu.queue.manage')
  })

  it('never blames another module for a patient failure', async () => {
    const api = await withApi()
    fetchMock.mockRejectedValue(denied('patients.read'))

    await expect(api.get('/api/v1/patients')).rejects.toMatchObject({ statusCode: 403 })

    const [toast] = toasts()
    expect(toast.description).toContain('Patients')
    expect(toast.description).toContain('patients.read')
    expect(toast.description).not.toContain('Verifactu')
  })

  it('uses the caller-supplied operation label when one is given', async () => {
    const api = await withApi()
    fetchMock.mockRejectedValue(denied('risk_engine.generate'))

    await expect(
      api.post(`/api/v1/risk_engine/patients/${RECORD_ID}`, {}, { operation: 'Generar evaluación de riesgo' })
    ).rejects.toMatchObject({ statusCode: 403 })

    const [toast] = toasts()
    expect(toast.description).toContain('Generar evaluación de riesgo')
    expect(toast.description).toContain('risk_engine.generate')
  })

  it('reports server and network failures with the same context', async () => {
    const api = await withApi()

    fetchMock.mockRejectedValue(httpError(503, 'AI provider unavailable'))
    await expect(api.post('/api/v1/copilot/chat')).rejects.toMatchObject({ statusCode: 503 })
    expect(toasts()[0]?.description).toContain('Copilot')

    _resetApiErrorNotifications()
    toastSpy.mockReset()

    fetchMock.mockRejectedValue(Object.assign(new TypeError('Failed to fetch'), { name: 'TypeError' }))
    await expect(api.get('/api/v1/agenda/appointments')).rejects.toBeTruthy()
    expect(toasts()[0]?.description).toContain('Agenda')
  })
})

describe('useApi — statuses the caller owns are not re-reported', () => {
  it('stays quiet for 404 / 409 / 422 so inline states remain the single source', async () => {
    const api = await withApi()

    for (const status of [404, 409, 422]) {
      fetchMock.mockRejectedValue(httpError(status, 'handled by the caller'))
      await expect(api.get(`/api/v1/patients/${RECORD_ID}`)).rejects.toMatchObject({ statusCode: status })
    }

    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('does not turn a cancelled request into an authorization failure', async () => {
    const api = await withApi()
    const controller = new AbortController()
    controller.abort()
    fetchMock.mockRejectedValue(Object.assign(new Error('aborted'), { name: 'AbortError' }))

    await expect(
      api.get('/api/v1/patients', { signal: controller.signal })
    ).rejects.toMatchObject({ name: 'AbortError' })

    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('does not stack identical notifications from a polling probe', async () => {
    const api = await withApi()
    fetchMock.mockRejectedValue(httpError(500, 'boom'))

    // Non-silent on purpose: the point is that even a *reported* failure
    // cannot pile up once per poll tick.
    for (let i = 0; i < 3; i++) {
      await expect(api.get('/api/v1/verifactu/health')).rejects.toMatchObject({ statusCode: 500 })
    }

    expect(toasts()).toHaveLength(1)
  })
})

describe('useApi — session recovery keeps the original operation', () => {
  it('refreshes once on 401 and retries the request that failed', async () => {
    const { useCookie } = await import('#app')
    useCookie('access_token').value = 'expired-token'
    useCookie('refresh_token').value = 'valid-refresh'
    // Cookie writes flush on the next tick; useAuth reads document.cookie
    // when it is created, so the component must mount after that.
    await nextTick()

    const refreshCalls: string[] = []

    // Installed *before* mounting: the app's own auth init runs during
    // mount and would otherwise clear the session state under test.
    fetchMock.mockImplementation(async (url: string, opts?: { headers?: Record<string, string> }) => {
      if (url.includes('/auth/refresh')) {
        refreshCalls.push(url)
        return {
          access_token: 'fresh-token',
          refresh_token: 'rotated-refresh',
          user: { id: 'u-1', email: 'dentist@demo.clinic' }
        }
      }
      if (url.includes('/auth/me')) {
        return {
          data: {
            user: { id: 'u-1', email: 'dentist@demo.clinic' },
            permissions: ['patients.read'],
            clinics: []
          }
        }
      }
      if (url.includes('/api/v1/patients')) {
        if (opts?.headers?.Authorization === 'Bearer fresh-token') return { data: [] }
        throw httpError(401, 'Not authenticated')
      }
      throw httpError(404, 'unexpected url')
    })

    const api = await withApi()

    await expect(api.get<{ data: unknown[] }>('/api/v1/patients')).resolves.toEqual({ data: [] })
    expect(refreshCalls).toHaveLength(1)
    expect(toastSpy).not.toHaveBeenCalled()

    useCookie('access_token').value = null
    useCookie('refresh_token').value = null
    await nextTick()
  })
})
