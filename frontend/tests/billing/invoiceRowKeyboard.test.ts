import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import PatientBillingSummary from '../../module_layers/billing/frontend/components/clinical/PatientBillingSummary.vue'

/**
 * The invoice rows in a patient's billing summary.
 *
 * The whole row is the click target for expanding an invoice and reading its
 * payments, and `cursor-pointer` said so — but a row is not focusable, so a
 * keyboard user could tab straight past the invoices of the patient in front of
 * them. Enter and Space now do what a click does, the row is in the tab order,
 * and `aria-expanded` says whether the payments underneath are showing.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const INVOICES_URL = '/api/v1/billing/invoices'

let requested: string[] = []

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  requested = []
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']

  fetchMock.mockImplementation(async (url: string) => {
    const full = String(url)
    requested.push(full)
    // The payments link lives under the invoices path, so it is matched first.
    if (full.includes('/payments')) return { data: [] }
    if (full.includes(INVOICES_URL)) {
      return {
        data: [{ id: 'inv-1', invoice_number: 'FV-2026-0001', total_amount: 120, status: 'sent' }],
        total: 1
      }
    }
    return { data: null }
  })
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('patient billing summary — invoice rows are operable without a mouse', () => {
  it('Enter expands the row and reads its payments, Space collapses it again', async () => {
    const wrapper = await mountSuspended(PatientBillingSummary, {
      props: { patientId: 'pat-1' }
    })
    await flush()

    const row = wrapper.get('tbody tr[tabindex="0"]')
    expect(row.attributes('aria-expanded')).toBe('false')

    await row.trigger('keydown.enter')
    await flush()
    await flush()

    expect(wrapper.get('tbody tr[tabindex="0"]').attributes('aria-expanded')).toBe('true')
    // Expanding is not cosmetic: it went and read the invoice's payments.
    expect(requested.some(u => u.includes('/payments'))).toBe(true)

    await wrapper.get('tbody tr[tabindex="0"]').trigger('keydown.space')
    await flush()

    expect(wrapper.get('tbody tr[tabindex="0"]').attributes('aria-expanded')).toBe('false')
  })

  it('a click still works, and the row reports itself as a row', async () => {
    const wrapper = await mountSuspended(PatientBillingSummary, {
      props: { patientId: 'pat-1' }
    })
    await flush()

    const row = wrapper.get('tbody tr[tabindex="0"]')
    // A row keeps its table semantics — it is focusable and expandable, not a
    // button pretending to be a row.
    expect(row.attributes('role')).toBeUndefined()

    await row.trigger('click')
    await flush()
    await flush()

    expect(wrapper.get('tbody tr[tabindex="0"]').attributes('aria-expanded')).toBe('true')
  })
})
