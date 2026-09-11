import { h, defineComponent, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { usePublicBudget } from '../../module_layers/budget/frontend/composables/usePublicBudget'

/**
 * The patient-facing budget page (`/p/budget/<token>`) talks to public
 * endpoints with **raw `$fetch`**: no `useApi`, so no shared toast, no error
 * shaping, nothing. Both loaders were `try/finally` with no `catch`, so a
 * failure rejected out of `onMounted` and left `meta` null — which the
 * template renders as loading skeletons, forever.
 *
 * A patient clicking a valid link during a network blip, or after the token
 * was purged, had no way to tell "still loading" from "this is never going to
 * work, call the clinic".
 */

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))

mockNuxtImport('$fetch', () => fetchMock)

/**
 * The client NProgress plugin removes its bar from nested ~200ms timers. This
 * file used to finish before they fired, so the callback ran after the test
 * environment was torn down and vitest reported `ReferenceError: document is
 * not defined` as an unhandled error — which fails the whole run even though
 * every test passed. Stubbing the module removes the timers rather than
 * racing them.
 */
vi.mock('nprogress', () => ({
  default: {
    configure: () => {},
    start: () => {},
    done: () => {},
    remove: () => {},
    isStarted: () => false,
    set: () => {},
    inc: () => {},
    trickle: () => {}
  }
}))

const TOKEN = 'b7d41f0a-9c2e-4a55-8f31-6d0e2c4b8a17'

function httpError(status: number) {
  return Object.assign(new Error(`request failed with ${status}`), {
    statusCode: status,
    status
  })
}

/** Fail only the public budget endpoints — app boot shares this mock. */
function failPublic(status: number | 'network'): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes('/budget/public/budgets/')) {
      throw status === 'network'
        ? Object.assign(new TypeError('Failed to fetch'), { name: 'TypeError' })
        : httpError(status)
    }
    return { data: null }
  })
}

const META = {
  requires_verification: false,
  method: 'none',
  locked: false,
  expired: false,
  already_decided: false,
  decided_status: null,
  clinic_name: 'Clínica Dental',
  clinic_phone: '+34 910 000 000',
  clinic_email: null,
  clinic_address_line: null,
  clinic_language: 'es',
  clinic_currency: 'EUR',
  patient_first_name: 'Ana',
  budget_number: 'P-2026-001',
  budget_total: '1250.00',
  valid_until: null
}

async function inSetup<T>(factory: () => T): Promise<T> {
  let value!: T
  const Passthrough: Component = defineComponent({
    setup() {
      value = factory()
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return value
}

beforeEach(() => {
  fetchMock.mockReset()
})

afterEach(() => {
  fetchMock.mockReset()
})

describe('public budget — a failed load is reported, not spun on forever', () => {
  it('never rejects out of the page and flags an unknown token', async () => {
    failPublic(404)
    const publicBudget = await inSetup(() => usePublicBudget(TOKEN))

    await expect(publicBudget.fetchMeta()).resolves.toBeUndefined()

    expect(publicBudget.loadError.value).toBe('not_found')
    expect(publicBudget.meta.value).toBeNull()
    expect(publicBudget.loading.value).toBe(false)
  })

  it('maps an expired link (410) and a locked link (403/423)', async () => {
    failPublic(410)
    const expired = await inSetup(() => usePublicBudget(TOKEN))
    await expired.fetchMeta()
    expect(expired.loadError.value).toBe('expired')

    failPublic(423)
    const locked = await inSetup(() => usePublicBudget(TOKEN))
    await locked.fetchMeta()
    expect(locked.loadError.value).toBe('locked')
  })

  it('reports a network failure as generic, with loading cleared', async () => {
    failPublic('network')
    const publicBudget = await inSetup(() => usePublicBudget(TOKEN))

    await publicBudget.fetchMeta()

    expect(publicBudget.loadError.value).toBe('generic')
    expect(publicBudget.loading.value).toBe(false)
  })

  it('reports a failure of the budget body itself, not just the meta', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/meta')) return { data: META }
      if (String(url).includes('/budget/public/budgets/')) throw httpError(500)
      return { data: null }
    })

    const publicBudget = await inSetup(() => usePublicBudget(TOKEN))
    await publicBudget.fetchMeta()
    expect(publicBudget.loadError.value).toBeNull()

    await publicBudget.fetchBudget()
    expect(publicBudget.loadError.value).toBe('generic')
    expect(publicBudget.budget.value).toBeNull()
  })

  it('clears the error when the retry succeeds', async () => {
    failPublic('network')
    const publicBudget = await inSetup(() => usePublicBudget(TOKEN))
    await publicBudget.fetchMeta()
    expect(publicBudget.loadError.value).toBe('generic')

    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/meta')) return { data: META }
      return { data: null }
    })

    await publicBudget.fetchMeta()

    expect(publicBudget.loadError.value).toBeNull()
    expect(publicBudget.meta.value?.patient_first_name).toBe('Ana')
  })
})
