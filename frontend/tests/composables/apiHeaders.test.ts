import { h, defineComponent, nextTick, type Component, type Ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useCookie } from '#app'
import { useApiHeaders } from '~/composables/useApiHeaders'
import { useSelectedClinicId } from '~/composables/useSelectedClinicId'

/**
 * Blob/array-buffer downloads, SSE streams and `<img>` thumbnails cannot go
 * through `useApi`, so they build their own headers. Thirteen such call sites
 * sent `Authorization` alone.
 *
 * Why that is a defect and not a detail: with no `X-Clinic-Id`, the backend's
 * `select_clinic` falls back to the user's **alphabetically-first membership**.
 * A dentist who belongs to two clinics therefore resolves the other clinic's
 * role — so the permission check runs against grants they are not using, and
 * per-clinic documents (invoice/budget PDF, accounting export) come back with
 * the wrong letterhead. Nothing errors, which is what made it invisible.
 */

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))

// App boot calls `/auth/me`; unmocked it fails and the auth flow clears the
// very session this test inspects.
mockNuxtImport('$fetch', () => fetchMock)

const CLINIC_ID = '6f1c2d34-5a6b-4c7d-8e9f-0a1b2c3d4e5f'
const OTHER_CLINIC_ID = '11111111-2222-3333-4444-555555555555'

interface Session {
  headers: ReturnType<typeof useApiHeaders>
  token: Ref<string | null | undefined>
  clinic: Ref<string | null | undefined>
}

/**
 * Both refs are captured inside the component so the test writes to the exact
 * instances `useApiHeaders` reads.
 */
async function withSession(): Promise<Session> {
  let session!: Session
  const Passthrough: Component = defineComponent({
    setup() {
      session = {
        headers: useApiHeaders(),
        token: useCookie<string | null>('access_token') as Ref<string | null | undefined>,
        clinic: useSelectedClinicId() as Ref<string | null | undefined>
      }
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return session
}

/**
 * Cookie writes are deferred: `useCookie(...).value = x` reaches the shared
 * ref a tick (or two) later, so assertions poll instead of assuming.
 */
async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes('/auth/me')) {
      return {
        data: {
          user: { id: 'u-1', email: 'dentist@demo.clinic' },
          permissions: ['patients.read'],
          clinics: [{ id: CLINIC_ID, name: 'Clinic One', role: 'dentist' }]
        }
      }
    }
    return { data: null }
  })
})

afterEach(() => {
  fetchMock.mockReset()
})

describe('useApiHeaders — requests outside useApi stay clinic-scoped', () => {
  it('sends the bearer token and the selected clinic', async () => {
    const session = await withSession()
    session.token.value = 'token-abc'
    session.clinic.value = CLINIC_ID
    await flush()

    await vi.waitFor(() => {
      expect(session.headers()).toEqual({
        'Authorization': 'Bearer token-abc',
        'X-Clinic-Id': CLINIC_ID
      })
    })
  })

  it('keeps caller-supplied headers alongside the clinic selection', async () => {
    const session = await withSession()
    session.token.value = 'token-abc'
    session.clinic.value = CLINIC_ID
    await flush()

    await vi.waitFor(() => {
      expect(session.headers({ 'Content-Type': 'application/json', 'Accept': 'text/event-stream' }))
        .toEqual({
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          'Authorization': 'Bearer token-abc',
          'X-Clinic-Id': CLINIC_ID
        })
    })
  })

  it('follows a clinic switch without remounting the screen', async () => {
    const session = await withSession()
    session.token.value = 'token-abc'
    session.clinic.value = CLINIC_ID
    await flush()
    await vi.waitFor(() => {
      expect(session.headers()['X-Clinic-Id']).toBe(CLINIC_ID)
    })

    // Read at call time, not captured once: the switcher changes the selection
    // and the very next download must follow it.
    session.clinic.value = OTHER_CLINIC_ID
    await flush()

    await vi.waitFor(() => {
      expect(session.headers()['X-Clinic-Id']).toBe(OTHER_CLINIC_ID)
    })
  })

  it('omits Authorization when signed out and never invents a clinic', async () => {
    const session = await withSession()
    session.token.value = null
    session.clinic.value = null
    await flush()

    await vi.waitFor(() => {
      expect(session.headers()).toEqual({})
    })
  })
})
