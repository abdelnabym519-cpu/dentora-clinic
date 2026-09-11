import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useReports } from '../../module_layers/reports/frontend/composables/useReports'
import { useHomeReports } from '../../module_layers/reports/frontend/composables/useHomeReports'
import CashCollectedTile from '../../module_layers/reports/frontend/components/dashboard/CashCollectedTile.vue'
import OverdueHeroTile from '../../module_layers/reports/frontend/components/home/OverdueHeroTile.vue'
import OverdueInvoicesPanel from '../../module_layers/reports/frontend/components/home/OverdueInvoicesPanel.vue'
import BillingReportPage from '../../module_layers/reports/frontend/pages/reports/billing.vue'

/**
 * A report that could not be read must not look like a clinic with nothing to
 * report.
 *
 * Every fetcher in `useReports` caught its failure, logged it and resolved to
 * `null`/`[]`. The pages then rendered the *absence* of data as a fact:
 * zeros, "No data" cards, a missing invoice-numbering-gap alert, and — worst —
 * a green "No overdue invoices" all-clear on both the billing report and the
 * home dashboard. A receptionist without `reports.billing.read` saw a clinic
 * that owed nobody anything. The dashboard went further: `useDashboardSnapshot`
 * tracked a per-card `error` flag that no component ever rendered.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

function denied(permission: string) {
  return Object.assign(new Error(`Permission denied: ${permission}`), {
    statusCode: 403,
    status: 403,
    data: { detail: `Permission denied: ${permission}` }
  })
}

/** Fail every URL containing one of the fragments — app boot shares the mock. */
function failUrls(fragments: string[], permission: string): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (fragments.some(f => String(url).includes(f))) throw denied(permission)
    return { data: null }
  })
}

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

const OVERDUE_URL = '/api/v1/reports/billing/overdue'

beforeEach(() => {
  _resetApiErrorNotifications()
  // useState survives between tests here: the home widgets share these keys.
  useState<unknown[]>('reports.home:overdue', () => []).value = []
  useState<boolean>('reports.home:overdue-loaded', () => false).value = false
  useState<string | null>('reports.home:overdue-error', () => null).value = null
  useState<string[]>('auth:permissions', () => []).value = ['*']
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('useReports — a failed section is recorded, not flattened to "no data"', () => {
  it('keeps the [] contract but says which section failed and why', async () => {
    failUrls([OVERDUE_URL], 'reports.billing.read')
    const reports = await inSetup(() => useReports())

    await expect(reports.fetchOverdueInvoices()).resolves.toEqual([])

    expect(reports.errors.value.overdueInvoices).toContain('reports.billing.read')
    expect(reports.hasErrors.value).toBe(true)
    expect(reports.failedSections.value).toEqual(['overdueInvoices'])
    expect(reports.errorSummary.value).toContain('reports.billing.read')
    // Silent at the API layer: the page renders the reason inline, and one
    // page load used to be able to fire six toasts.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('collapses a whole failed page load into one line', async () => {
    failUrls(['/api/v1/reports/'], 'reports.billing.read')
    const reports = await inSetup(() => useReports())

    await Promise.all([
      reports.fetchBillingSummary('2026-01-01', '2026-01-31'),
      reports.fetchOverdueInvoices(),
      reports.fetchNumberingGaps()
    ])

    expect(reports.failedSections.value).toHaveLength(3)
    expect(reports.errorSummary.value).toMatch(/\(\+2\)$/)
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('clears on a retry that succeeds', async () => {
    failUrls([OVERDUE_URL], 'reports.billing.read')
    const reports = await inSetup(() => useReports())

    await reports.fetchOverdueInvoices()
    expect(reports.hasErrors.value).toBe(true)

    reports.clearErrors()
    fetchMock.mockImplementation(async () => ({ data: [] }))
    await reports.fetchOverdueInvoices()

    expect(reports.hasErrors.value).toBe(false)
    expect(reports.errorSummary.value).toBeUndefined()
  })
})

describe('the home dashboard never all-clears a failed read', () => {
  it('useHomeReports distinguishes "nothing overdue" from "could not read"', async () => {
    failUrls([OVERDUE_URL], 'reports.billing.read')
    const home = await inSetup(() => useHomeReports())

    await expect(home.loadOverdue()).resolves.toEqual([])

    expect(home.overdueError.value).toContain('reports.billing.read')
    expect(home.overdueLoaded.value).toBe(true)
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('the attention panel shows the failure with a Retry, not a green all-clear', async () => {
    failUrls([OVERDUE_URL], 'reports.billing.read')

    const wrapper = await mountSuspended(OverdueInvoicesPanel)
    await flush()

    expect(wrapper.find('[data-testid="overdue-panel-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="overdue-panel-retry"]').exists()).toBe(true)
    // The double-check "nothing is overdue" illustration must be gone.
    expect(wrapper.html()).not.toContain('check-check')
  })

  it('the hero tile shows an unknown count, not zero', async () => {
    failUrls([OVERDUE_URL], 'reports.billing.read')

    const wrapper = await mountSuspended(OverdueHeroTile)
    await flush()

    const error = wrapper.find('[data-testid="overdue-hero-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toBe('—')
    expect(wrapper.text()).not.toContain('0')
  })
})

describe('a dashboard card renders its error flag', () => {
  it('shows the failure instead of the empty slot', async () => {
    const wrapper = await mountSuspended(CashCollectedTile, {
      props: {
        state: { loading: false, error: true, data: null, delta: null, spark: [] }
      }
    })

    expect(wrapper.find('[data-testid="summary-card-error"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('—')
  })

  it('still shows "no data" when the read succeeded and there is none', async () => {
    const wrapper = await mountSuspended(CashCollectedTile, {
      props: {
        state: { loading: false, error: false, data: null, delta: null, spark: [] }
      }
    })

    expect(wrapper.find('[data-testid="summary-card-error"]').exists()).toBe(false)
  })
})

describe('the billing report page reports a failed load', () => {
  it('renders the alert and the overdue failure, never the green all-clear', async () => {
    failUrls(['/api/v1/reports/'], 'reports.billing.read')

    const wrapper = await mountSuspended(BillingReportPage)
    await flush()
    await flush()

    expect(wrapper.find('[data-testid="reports-load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="reports-retry"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="report-overdue-error"]').exists()).toBe(true)
    // The numbering-gap check never ran, so it must not look clean either.
    expect(wrapper.find('[data-testid="report-gaps-error"]').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('check-circle')
    expect(toastSpy).not.toHaveBeenCalled()
  })
})
