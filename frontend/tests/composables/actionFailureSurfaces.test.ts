import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { PERMISSIONS } from '~/config/permissions'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useKapso } from '../../module_layers/whatsapp_kapso/frontend/composables/useKapso'
import { usePeriodontogramSession } from '../../module_layers/periodontogram/frontend/composables/usePeriodontogramSession'
import { useClinicalNotes } from '../../module_layers/clinical_notes/frontend/composables/useClinicalNotes'
import { useInvoices } from '../../module_layers/billing/frontend/composables/useInvoices'
import KapsoSettingsPage from '../../module_layers/whatsapp_kapso/frontend/components/KapsoSettingsPage.vue'
import AppointmentNotesPanel from '../../module_layers/clinical_notes/frontend/components/AppointmentNotesPanel.vue'

/**
 * An action or a panel load that fails has to be *visible where it happened*.
 *
 * Every site below was `try/finally` with no `catch` around a direct API
 * call, so the rejection escaped the click handler / `onMounted` and the UI
 * fell through to whatever it renders when there is simply no data:
 *
 * - WhatsApp settings rendered a form built from blanks, with a live Save
 *   that would have overwritten the clinic's stored phone number and secrets;
 * - closing or discarding a periodontogram session dismissed the dialog and
 *   left the draft untouched, with no message at all for a 409/422;
 * - the appointment notes panel rendered "no notes for this appointment" —
 *   a clinical claim nobody had established;
 * - an expanded invoice row rendered "No payments" — a financial claim.
 *
 * Where the consumer owns an inline surface, the API call is `{ silent }` so
 * the failure is reported exactly once, with the server's own reason.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const KAPSO_SETTINGS_URL = '/api/v1/whatsapp_kapso/settings'
const PERIO_CLOSE_URL = '/close'
const PERIO_SNAPSHOT_URL = '/api/v1/periodontogram/snapshots/'
const NOTES_URL = '/api/v1/clinical_notes/notes'
const INVOICE_PAYMENTS_URL = '/api/v1/billing/invoices/inv-1/payments'

function failure(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    statusCode: status,
    status,
    data: { detail }
  })
}

/** Fail only the URL under test — app boot traffic shares this mock. */
function failUrl(fragment: string, status: number, detail: string): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes(fragment)) throw failure(status, detail)
    return { data: null }
  })
}

/** Let a bare `onMounted(...)` / immediate watcher settle. */
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
  // useState survives between tests in this environment: start from clean.
  useState<unknown>('kapso:settings', () => null).value = null
  useState<unknown[]>('kapso:templates', () => []).value = []
  useState<string[]>('auth:permissions', () => []).value = ['*']
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('WhatsApp (Kapso) settings — a failed read is not a blank form', () => {
  it('exposes the reason, keeps settings null, and does not reject', async () => {
    failUrl(KAPSO_SETTINGS_URL, 403, 'Permission denied: whatsapp_kapso.settings.read')
    const kapso = await inSetup(() => useKapso())

    // The page calls it bare from onMounted, so it must never throw.
    await expect(kapso.fetchSettings()).resolves.toBeUndefined()

    expect(kapso.error.value).toContain('whatsapp_kapso.settings.read')
    expect(kapso.settings.value).toBeNull()
    expect(kapso.loading.value).toBe(false)
    // The page renders the reason inline: the shared toast stays quiet.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('renders the failure with a Retry instead of the secrets form', async () => {
    failUrl(KAPSO_SETTINGS_URL, 403, 'Permission denied: whatsapp_kapso.settings.read')

    const wrapper = await mountSuspended(KapsoSettingsPage)
    await flush()

    expect(wrapper.find('[data-testid="kapso-settings-load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="kapso-settings-retry"]').exists()).toBe(true)
    // The API-key and webhook-secret inputs must not be reachable while the
    // stored values are unknown — one Save would blank them.
    expect(wrapper.findAll('input[type="password"]')).toHaveLength(0)
    // Only the Retry button survives.
    expect(wrapper.findAll('button')).toHaveLength(1)
  })

  it('leaves the save failure to the page, so it is reported once', async () => {
    failUrl(KAPSO_SETTINGS_URL, 422, 'phone_number_id must be a non-empty string')
    const kapso = await inSetup(() => useKapso())

    await expect(kapso.saveSettings({ phone_number_id: '' })).rejects.toBeTruthy()

    // onSave() catches and toasts `saveError` + the server's detail; a second
    // toast from the shared layer would be the same failure reported twice.
    expect(toastSpy).not.toHaveBeenCalled()
  })
})

describe('periodontogram session — a failed close or discard is visible', () => {
  it('closeSession reports the conflict and still rejects', async () => {
    failUrl(PERIO_CLOSE_URL, 409, 'Snapshot is already closed')
    const session = await inSetup(() => usePeriodontogramSession())

    // Rejecting is what stops the chart from emitting `closed` and treating
    // the draft as finished.
    await expect(session.closeSession('snap-1', 'final notes')).rejects.toBeTruthy()

    expect(session.lastError.value).toBe('Snapshot is already closed')
    expect(session.saving.value).toBe(false)
    // Reported once, by the chart's save-failed toast, carrying this reason.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('discardDraft reports the conflict and still rejects', async () => {
    failUrl(PERIO_SNAPSHOT_URL, 409, 'Snapshot belongs to a closed session')
    const session = await inSetup(() => usePeriodontogramSession())

    await expect(session.discardDraft('snap-2')).rejects.toBeTruthy()

    expect(session.lastError.value).toBe('Snapshot belongs to a closed session')
    expect(session.saving.value).toBe(false)
    expect(toastSpy).not.toHaveBeenCalled()
  })
})

describe('clinical notes — a failed load is not "no notes"', () => {
  it('hands the reason to the panel and stays quiet at the shared layer', async () => {
    failUrl(NOTES_URL, 404, 'Appointment not found')
    const notes = await inSetup(() => useClinicalNotes())

    await expect(
      notes.listForOwner('appointment', 'apt-1', { silent: true })
    ).rejects.toBeTruthy()

    expect(toastSpy).not.toHaveBeenCalled()
    expect(notes.loading.value).toBe(false)
  })

  it('the appointment panel renders the failure, not the empty state', async () => {
    failUrl(NOTES_URL, 404, 'Appointment not found')

    const wrapper = await mountSuspended(AppointmentNotesPanel, {
      props: { ctx: { appointmentId: 'apt-1', patientId: 'pat-1' } }
    })
    await flush()

    expect(wrapper.find('[data-testid="appointment-notes-load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="appointment-notes-retry"]').exists()).toBe(true)
    // The "no notes for this appointment" illustration must be gone: that
    // empty state is a clinical claim, and the load never succeeded.
    expect(wrapper.html()).not.toContain('notebook-pen')
  })
})

describe('billing — an unreadable payment list is not "no payments"', () => {
  it('fetchPayments rejects instead of resolving to an empty list', async () => {
    failUrl(INVOICE_PAYMENTS_URL, 403, 'Permission denied: payments.read')
    const invoices = await inSetup(() => useInvoices())

    // An empty array has to mean "this invoice has no payments". The old
    // catch made a denial indistinguishable from that, and the expanded row
    // rendered it as a financial claim.
    await expect(invoices.fetchPayments('inv-1')).rejects.toBeTruthy()
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('the clinical-notes permission constant still gates the panel', () => {
    // Guard against the panel silently rendering nothing in the test above
    // for the wrong reason (a missing grant rather than a handled failure).
    expect(PERMISSIONS.clinicalNotes.read).toBeTruthy()
  })
})
