import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import PatientBillingSummary from '../../module_layers/billing/frontend/components/clinical/PatientBillingSummary.vue'

/**
 * The patient billing summary's invoice list.
 *
 * A denied read used to be indistinguishable from a patient who genuinely has
 * no invoices: `loadInvoices` caught, emptied the list and set the total to 0,
 * and the template rendered its "no invoices" empty state — a financial claim
 * nobody had established, with a "create the first invoice" button under it.
 * It now renders the reason with a Retry, and the two states are mutually
 * exclusive branches of the same `v-if` chain.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const INVOICES_URL = '/api/v1/billing/invoices'

function failure(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), { statusCode: status, status, data: { detail } })
}

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('patient billing summary — the invoice list reports its own failure', () => {
  it('shows the reason and a Retry instead of "this patient has no invoices"', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes(INVOICES_URL)) {
        throw failure(403, 'Permission denied: billing.invoices.read')
      }
      return { data: null }
    })

    const wrapper = await mountSuspended(PatientBillingSummary, {
      props: { patientId: 'pat-1' }
    })
    await flush()

    const alert = wrapper.find('[data-testid="patient-invoices-load-error"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('Permission denied: billing.invoices.read')
    expect(wrapper.find('[data-testid="patient-invoices-retry"]').exists()).toBe(true)

    // The empty state and the table are the other two branches of the chain.
    expect(wrapper.find('table').exists()).toBe(false)

    // The component owns the surface: one failure, one report, no global toast.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('clears the failure and renders the list when the Retry succeeds', async () => {
    let denied = true
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes(INVOICES_URL)) {
        if (denied) throw failure(403, 'Permission denied: billing.invoices.read')
        return {
          data: [{ id: 'inv-1', invoice_number: 'FV-2026-0001', total_amount: 120, status: 'paid' }],
          total: 1
        }
      }
      return { data: null }
    })

    const wrapper = await mountSuspended(PatientBillingSummary, {
      props: { patientId: 'pat-1' }
    })
    await flush()
    expect(wrapper.find('[data-testid="patient-invoices-load-error"]').exists()).toBe(true)

    denied = false
    await wrapper.find('[data-testid="patient-invoices-retry"]').trigger('click')
    await flush()
    await flush()

    expect(wrapper.find('[data-testid="patient-invoices-load-error"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('FV-2026-0001')
  })
})
