import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useClinicalNotes } from '../../module_layers/clinical_notes/frontend/composables/useClinicalNotes'
import { usePeriodontogram } from '../../module_layers/periodontogram/frontend/composables/usePeriodontogram'
import { useClinicHours } from '../../module_layers/schedules/frontend/composables/useClinicHours'
import PatientClinicalNotesByPlan from '../../module_layers/clinical_notes/frontend/components/PatientClinicalNotesByPlan.vue'
import ClinicHoursPage from '../../module_layers/schedules/frontend/components/settings/ClinicHoursPage.vue'
import CopilotDrawer from '../../module_layers/copilot/frontend/components/CopilotDrawer.vue'
import CopilotComposer from '../../module_layers/copilot/frontend/components/CopilotComposer.vue'
import CopilotNudges from '../../module_layers/copilot/frontend/components/CopilotNudges.vue'
import CopilotPending from '../../module_layers/copilot/frontend/components/CopilotPending.vue'

/**
 * The last class of silent failure: an action or a panel load whose callee had
 * **no catch at all**, so the rejection escaped a click handler / an immediate
 * watcher as an unhandled promise rejection, and the UI showed whatever it
 * shows when there is simply nothing there.
 *
 * The two worst were data-loss and message-loss:
 * - the clinic-hours settings page rendered its weekly grid from empty
 *   defaults with a live Save, one click from overwriting the real opening
 *   hours;
 * - the Copilot composer cleared the clinician's message *before* sending, so
 *   a failure to create the session destroyed what they had typed.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

function failure(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), { statusCode: status, status, data: { detail } })
}

function failUrl(fragment: string, status: number, detail: string): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes(fragment)) throw failure(status, detail)
    return { data: null }
  })
}

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
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

const PLAN_NOTES_URL = '/api/v1/clinical_notes/treatment-plans/plan-1/merged'
const PATIENT_NOTES_URL = '/api/v1/clinical_notes/patients/pat-1/by-plan'
const PERIO_DRAFT_URL = '/api/v1/periodontogram/patients/pat-1/draft'
const PERIO_SNAPSHOT_URL = '/api/v1/periodontogram/snapshots/snap-1'
const CLINIC_HOURS_URL = '/api/v1/schedules/clinic-hours'
const OVERRIDE_URL = '/api/v1/schedules/clinic-overrides/ovr-1'
const COPILOT_SESSION_URL = '/api/v1/copilot/sessions'

beforeEach(() => {
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('clinical notes — a read that never had a catch', () => {
  it('listMergedForPlan resolves, records the reason, and stays quiet', async () => {
    failUrl(PLAN_NOTES_URL, 403, 'Permission denied: clinical_notes.read')
    const notes = await inSetup(() => useClinicalNotes())

    await expect(notes.listMergedForPlan('plan-1', { silent: true })).resolves.toEqual([])

    expect(notes.error.value).toContain('clinical_notes.read')
    expect(notes.loading.value).toBe(false)
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('the patient notes tab shows the failure, not "no clinical notes"', async () => {
    failUrl(PATIENT_NOTES_URL, 404, 'Patient not found')

    const wrapper = await mountSuspended(PatientClinicalNotesByPlan, {
      props: { ctx: { patientId: 'pat-1' } }
    })
    await flush()

    expect(wrapper.find('[data-testid="patient-notes-load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="patient-notes-retry"]').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('notebook-pen')
  })
})

describe('periodontogram — start and snapshot reads report through the view alert', () => {
  it('startDraft surfaces a 409 and still rejects', async () => {
    failUrl(PERIO_DRAFT_URL, 409, 'A draft session already exists')
    const perio = await inSetup(() => usePeriodontogram(() => 'pat-1'))

    await expect(perio.startDraft()).rejects.toBeTruthy()

    expect(perio.error.value).toBe('A draft session already exists')
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('fetchSnapshot absorbs the failure so the date watcher cannot reject', async () => {
    failUrl(PERIO_SNAPSHOT_URL, 500, 'Snapshot storage unavailable')
    const perio = await inSetup(() => usePeriodontogram(() => 'pat-1'))

    await expect(perio.fetchSnapshot('snap-1')).resolves.toBeUndefined()

    expect(perio.error.value).toBe('Snapshot storage unavailable')
    expect(perio.currentSnapshot.value).toBeNull()
    expect(toastSpy).not.toHaveBeenCalled()
  })
})

describe('clinic hours — the page owns the report, and never renders a blank grid', () => {
  it('the composable is silent so one failure is reported once', async () => {
    failUrl(CLINIC_HOURS_URL, 403, 'Permission denied: schedules.clinic_hours.read')
    const hours = await inSetup(() => useClinicHours())

    await expect(hours.fetchHours()).rejects.toBeTruthy()
    expect(toastSpy).not.toHaveBeenCalled()

    failUrl(OVERRIDE_URL, 409, 'Override no longer exists')
    await expect(hours.deleteOverride('ovr-1')).rejects.toBeTruthy()
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('a failed load hides the weekly grid and its Save button', async () => {
    failUrl(CLINIC_HOURS_URL, 403, 'Permission denied: schedules.clinic_hours.read')

    const wrapper = await mountSuspended(ClinicHoursPage)
    await flush()

    expect(wrapper.find('[data-testid="clinic-hours-load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="clinic-hours-retry"]').exists()).toBe(true)
    // Only Retry: saving an empty weekly template would erase the clinic's
    // real opening hours.
    expect(wrapper.findAll('button')).toHaveLength(1)
  })
})

describe('copilot — a failed send does not eat the message', () => {
  it('keeps the typed text in the composer when the session cannot be created', async () => {
    failUrl(COPILOT_SESSION_URL, 403, 'Permission denied: copilot.use')

    const wrapper = await mountSuspended(CopilotDrawer)
    await flush()

    const composer = wrapper.findComponent(CopilotComposer)
    expect(composer.exists()).toBe(true)

    composer.vm.$emit('update:modelValue', 'Review the risk engine output for tooth 36')
    await flush()
    composer.vm.$emit('submit')
    await flush()
    await flush()

    expect(composer.props('modelValue')).toBe('Review the risk engine output for tooth 36')
  })
})

describe('a null collection payload is an empty list, not a render crash', () => {
  // Every list ref in the app is fed straight from the response envelope. One
  // `{"data": null}` — an empty collection serialised as null by any layer in
  // between — used to reach `v-if="nudges.length"` and throw while rendering,
  // taking the whole drawer subtree down with it.
  it('the copilot nudges render nothing instead of throwing', async () => {
    fetchMock.mockResolvedValue({ data: null })

    const wrapper = await mountSuspended(CopilotNudges)
    await flush()

    expect(wrapper.text()).toBe('')
  })

  it('the copilot pending queue renders nothing instead of throwing', async () => {
    fetchMock.mockResolvedValue({ data: null })

    const wrapper = await mountSuspended(CopilotPending)
    await flush()

    // It reaches its empty state instead of throwing inside the render.
    // The copy itself is locale-dependent (the test app runs in Arabic), so
    // only the fact that something rendered is asserted here.
    expect(wrapper.find('*').exists()).toBe(true)
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
