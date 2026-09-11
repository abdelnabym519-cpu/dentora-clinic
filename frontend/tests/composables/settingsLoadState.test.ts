import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useBudgetSettings } from '../../module_layers/budget/frontend/composables/useBudgetSettings'
import { useCommunicationsSettings } from '../../module_layers/notifications/frontend/composables/useCommunicationsSettings'
import { useConversation } from '../../module_layers/notifications/frontend/composables/useConversation'
import BudgetRemindersPage from '../../module_layers/budget/frontend/components/settings/BudgetRemindersPage.vue'

/**
 * A settings screen that could not read its current values must say so —
 * it must not render the form.
 *
 * These composables used `try/finally` with no `catch`: the rejection
 * escaped the page's bare `onMounted(fetch)` as an unhandled promise
 * rejection, the only signal was a global toast, and the page went on to
 * render its switches and pickers from **defaults** (`reminders: off`,
 * `language: es`) with a live Save button — one click from writing a value
 * the clinic never chose. The WhatsApp conversation thread had the same
 * shape, where a failed load rendered as "no messages yet" and left the
 * reply box looking usable.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const BUDGET_URL = '/api/v1/auth/clinic/settings/budget'
const COMMS_URL = '/api/v1/auth/clinic/settings/communications'
const CONVERSATION_URL = '/api/v1/notifications/conversations'
const PATIENT_ID = '2f7a9c41-8d3e-4b6a-9f15-6c0d2e8a7b34'

function denied(permission: string) {
  return Object.assign(new Error(`Permission denied: ${permission}`), {
    statusCode: 403,
    status: 403,
    data: { detail: `Permission denied: ${permission}` }
  })
}

/** Fail only the URL under test — app boot traffic shares this mock. */
function failUrl(fragment: string, permission: string): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes(fragment)) throw denied(permission)
    return { data: null }
  })
}

/** Let a bare `onMounted(fetch)` settle. */
async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

/** These composables need a component setup context (useApi → i18n/toast). */
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
  _resetApiErrorNotifications()
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('a failed settings load reports instead of rendering defaults', () => {
  it('budget settings: resolves, exposes the reason, keeps settings null', async () => {
    failUrl(BUDGET_URL, 'admin.clinic.read')
    const budget = await inSetup(() => useBudgetSettings())

    // Must not reject: the page calls it bare from onMounted.
    await expect(budget.fetch()).resolves.toBeUndefined()

    expect(budget.error.value).toContain('admin.clinic.read')
    expect(budget.settings.value).toBeNull()
    expect(budget.loading.value).toBe(false)
    // The page renders the reason inline, so the shared toast stays quiet.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('communications settings: same contract', async () => {
    failUrl(COMMS_URL, 'admin.clinic.read')
    const comms = await inSetup(() => useCommunicationsSettings())

    await expect(comms.fetch()).resolves.toBeUndefined()

    expect(comms.error.value).toContain('admin.clinic.read')
    expect(comms.settings.value).toBeNull()
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('conversation thread: a failed load is not an empty thread', async () => {
    failUrl(CONVERSATION_URL, 'notifications.logs.read')
    const conv = await inSetup(() => useConversation(PATIENT_ID))

    await expect(conv.fetchThread()).resolves.toBeUndefined()

    expect(conv.error.value).toContain('notifications.logs.read')
    expect(conv.messages.value).toEqual([])
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('clears a previous failure when the retry succeeds', async () => {
    failUrl(BUDGET_URL, 'admin.clinic.read')
    const budget = await inSetup(() => useBudgetSettings())

    await budget.fetch()
    expect(budget.error.value).toBeTruthy()

    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes(BUDGET_URL)) {
        return {
          data: {
            budget_expiry_days: 45,
            plan_auto_close_days_after_expiry: 15,
            budget_reminders_enabled: true,
            budget_public_auth_disabled: false
          }
        }
      }
      return { data: null }
    })

    await budget.fetch()

    expect(budget.error.value).toBeNull()
    expect(budget.settings.value?.budget_reminders_enabled).toBe(true)
    expect(toastSpy).not.toHaveBeenCalled()
  })
})

describe('the budget reminders page renders the failure, not the form', () => {
  it('shows the inline error with a retry and no switch to save', async () => {
    failUrl(BUDGET_URL, 'admin.clinic.read')

    const wrapper = await mountSuspended(BudgetRemindersPage)
    await flush()

    expect(wrapper.find('[data-testid="budget-reminders-load-error"]').exists()).toBe(true)
    // The toggle and its Save button must not be reachable while the current
    // value is unknown — that is the whole point of the inline state.
    expect(wrapper.find('[role="switch"]').exists()).toBe(false)
    // Only the retry button survives.
    expect(wrapper.findAll('button')).toHaveLength(1)
  })
})
