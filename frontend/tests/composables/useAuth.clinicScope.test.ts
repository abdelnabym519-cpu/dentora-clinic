import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useAuth } from '~/composables/useAuth'

/**
 * Permissions are clinic-scoped: ``/auth/me`` resolves the role from the
 * ``X-Clinic-Id`` header, and every data request pins that same header.
 *
 * Before this was fixed, ``useAuth`` fetched ``/auth/me`` *without* the
 * clinic header while ``useApi`` sent it on every call — so a multi-clinic
 * user reloaded into clinic A's grant list while their clicks targeted
 * clinic B, and legitimately authorized actions came back 403 ("Access
 * denied" for something the user is allowed to do).
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const CLINIC_A = '11111111-1111-4111-8111-111111111111'
const CLINIC_B = '22222222-2222-4222-8222-222222222222'

interface MeCall {
  headers?: Record<string, string>
}

const meCalls: MeCall[] = []

function meResponse(permissions: string[], clinicIds: string[]) {
  return {
    data: {
      user: { id: 'u-1', email: 'dentist@demo.clinic', first_name: 'D', last_name: 'R' },
      permissions,
      clinics: clinicIds.map(id => ({ id, name: `Clinic ${id.slice(0, 4)}`, role: 'dentist' }))
    }
  }
}

/**
 * The backend mirrors ``select_clinic``: it answers with the grants of the
 * clinic named by X-Clinic-Id, falling back to the first membership.
 */
function stubMe(): void {
  fetchMock.mockImplementation(async (url: string, opts?: { headers?: Record<string, string> }) => {
    if (String(url).includes('/auth/me')) {
      meCalls.push({ headers: opts?.headers })
      const requested = opts?.headers?.['X-Clinic-Id']
      if (requested === CLINIC_B) return meResponse(['budget.read'], [CLINIC_A, CLINIC_B])
      return meResponse(['patients.read', 'budget.read'], [CLINIC_A, CLINIC_B])
    }
    return { data: [] }
  })
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

async function setCookies(access: string | null, clinicId: string | null): Promise<void> {
  const { useCookie } = await import('#app')
  useCookie('access_token').value = access
  useCookie('refresh_token').value = access ? 'refresh-token' : null
  useCookie('clinic_id').value = clinicId
  // Cookie writes flush on a tick and useAuth reads document.cookie.
  await nextTick()
}

beforeEach(() => {
  meCalls.length = 0
  fetchMock.mockReset()
  toastSpy.mockReset()
  stubMe()
})

afterEach(async () => {
  await setCookies(null, null)
})

describe('useAuth — clinic-scoped permission loading', () => {
  it('requests /auth/me for the clinic the data requests will target', async () => {
    await setCookies('token', CLINIC_B)
    const auth = await withAuth()

    await auth.fetchUser()

    const last = meCalls.at(-1)
    expect(last?.headers?.['X-Clinic-Id']).toBe(CLINIC_B)
    // …and stores the grants of *that* clinic, not the fallback one.
    expect(auth.permissions.value).toEqual(['budget.read'])
  })

  it('re-reads the grants when the stored clinic is not a membership', async () => {
    const stale = '33333333-3333-4333-8333-333333333333'
    await setCookies('token', stale)
    const auth = await withAuth()

    await auth.fetchUser()

    const { useSelectedClinicId } = await import('~/composables/useSelectedClinicId')
    // Cookie writes flush on a tick; read the selection after that.
    await nextTick()
    // Selection is repaired to a real membership…
    expect(useSelectedClinicId().value).toBe(CLINIC_A)
    // …and the grant list is resolved again for the corrected clinic, so
    // the UI never gates on a clinic the requests are not sent to.
    expect(meCalls.length).toBeGreaterThanOrEqual(2)
    expect(meCalls.at(-1)?.headers?.['X-Clinic-Id']).toBe(CLINIC_A)
    expect(auth.permissions.value).toContain('patients.read')
  })

  it('keeps working without a stored clinic selection', async () => {
    await setCookies('token', null)
    const auth = await withAuth()

    await auth.fetchUser()

    // With nothing selected the header is simply absent — the backend
    // falls back to the token's clinic — and permissions still load.
    expect(meCalls.some(call => call.headers?.['X-Clinic-Id'] === undefined)).toBe(true)
    expect(auth.permissions.value.length).toBeGreaterThan(0)
    // The first membership becomes the selection for subsequent requests.
    const { useSelectedClinicId } = await import('~/composables/useSelectedClinicId')
    await nextTick()
    expect(useSelectedClinicId().value).toBe(CLINIC_A)
  })
})
