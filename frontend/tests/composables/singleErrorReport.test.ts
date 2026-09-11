import { h, defineComponent, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useUsers } from '~/composables/useUsers'
import { useTreatmentCatalogSearch } from '~/composables/useTreatmentCatalogSearch'
import { useTreatmentPlans } from '../../module_layers/treatment_plan/frontend/composables/useTreatmentPlans'
import { useCatalog } from '../../module_layers/catalog/frontend/composables/useCatalog'
import type { UserCreate } from '~/types'

/**
 * One failed operation must produce exactly one report, and it must carry
 * the reason the server gave.
 *
 * Two defects lived here:
 *  - composables that toast in their own `catch` while `useApi` also toasted
 *    the same failure, so a single denied click stacked two error toasts
 *    (one generic, one labelled);
 *  - reads that swallowed the failure and returned an empty list, so an
 *    outage or a missing `catalog.read` rendered as "no data" — the user
 *    goes looking for a treatment that exists.
 *
 * The contract: an operation that owns its message silences the shared one
 * (`{ silent: true }`) *and* keeps the server detail; an operation that
 * renders an inline surface does the same through its own `error` ref.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const PLAN_ID = '9c4d1a7e-2b6f-4d18-9a05-7e3c1b8f6d21'

/** Shaped like ofetch's FetchError: status + parsed body under `.data`. */
function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(typeof detail === 'string' ? detail : 'request failed'), {
    statusCode: status,
    status,
    data: { detail }
  })
}

/** Exactly what the backend's `require_permission` answers with. */
function denied(permission: string) {
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

/** Composables must be created inside a Nuxt/i18n context. */
async function mounted<T>(factory: () => T): Promise<T> {
  let value!: T
  const Host: Component = defineComponent({
    setup() {
      value = factory()
      return () => h('div')
    }
  })
  await mountSuspended(Host)
  return value
}

beforeEach(() => {
  _resetApiErrorNotifications()
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('an operation that owns its message reports exactly once', () => {
  it('a denied user creation yields one toast naming the missing permission', async () => {
    const users = await mounted(() => useUsers())
    fetchMock.mockRejectedValue(denied('users.write'))

    const payload: UserCreate = {
      email: 'ana.sousa@clinica.test',
      password: 'secret-123',
      first_name: 'Ana',
      last_name: 'Sousa',
      role: 'dentist'
    }

    await expect(users.createUser(payload)).resolves.toBeNull()

    expect(toasts()).toHaveLength(1)
    expect(toasts()[0]?.color).toBe('error')
    expect(toasts()[0]?.description).toContain('users.write')
    // The inline field the settings page renders keeps the same reason.
    expect(users.error.value).toContain('users.write')
  })

  it('a denied treatment-plan deletion yields one toast with the server reason', async () => {
    const plans = await mounted(() => useTreatmentPlans())
    fetchMock.mockRejectedValue(denied('treatment_plans.write'))

    await expect(plans.deletePlan(PLAN_ID)).resolves.toBe(false)

    expect(toasts()).toHaveLength(1)
    expect(toasts()[0]?.color).toBe('error')
    expect(toasts()[0]?.description).toContain('treatment_plans.write')
  })

  it('keeps a conflict the caller owns as the single message', async () => {
    const plans = await mounted(() => useTreatmentPlans())
    fetchMock.mockRejectedValue(httpError(409, 'Plan is already closed'))

    await expect(plans.deletePlan(PLAN_ID)).resolves.toBe(false)

    // The shared layer never toasts 409; the composable must not drop it.
    expect(toasts()).toHaveLength(1)
    expect(toasts()[0]?.description).toContain('Plan is already closed')
  })
})

describe('an operation with an inline surface does not toast', () => {
  it('reports a denied catalog read through `error`, not a global toast', async () => {
    const catalog = await mounted(() => useCatalog())
    fetchMock.mockRejectedValue(denied('catalog.read'))

    await catalog.fetchItems({ pageSize: 10, silent: true })

    expect(toastSpy).not.toHaveBeenCalled()
    expect(catalog.error.value).toContain('catalog.read')
    expect(catalog.items.value).toEqual([])
  })

  it('tells a failed treatment search apart from an empty result', async () => {
    const search = await mounted(() => useTreatmentCatalogSearch())
    fetchMock.mockRejectedValue(denied('catalog.read'))

    // The "common treatments" suggestions are decoration inside a modal:
    // their failure must never toast over the workflow the user is in.
    await search.loadPopularItems()
    expect(toastSpy).not.toHaveBeenCalled()
    expect(search.popularItems.value).toEqual([])
    expect(search.loadError.value).toContain('catalog.read')

    await search.search('implant')
    expect(toastSpy).not.toHaveBeenCalled()
    expect(search.searchResults.value).toEqual([])
    // Swallowing this one used to render an outage as "no matches".
    expect(search.searchError.value).toContain('catalog.read')
  })
})
