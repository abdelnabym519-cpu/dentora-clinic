import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import ClinicHoursPage from '../../module_layers/schedules/frontend/components/settings/ClinicHoursPage.vue'
import OverrideCalendar from '../../module_layers/schedules/frontend/components/OverrideCalendar.vue'

/**
 * Double submit.
 *
 * The override modal's Save stayed clickable while its request was in flight,
 * so a second click created a *second* override for the same dates — two
 * contradictory closed-day entries for the clinic, and nothing on screen to say
 * why. The button now reports the pending state and the handler ignores a
 * second call until the first settles.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const HOURS_URL = '/api/v1/schedules/clinic-hours'
const OVERRIDES_URL = '/api/v1/schedules/clinic-overrides'

const CLINIC_HOURS = {
  id: 'ch-1',
  clinic_id: 'cl-1',
  timezone: 'UTC',
  is_active: true,
  days: [{ weekday: 1, shifts: [{ start: '09:00', end: '17:00' }] }]
}

let posted: string[] = []
let releaseCreate: ((value: unknown) => void) | null = null

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  posted = []
  releaseCreate = null
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']

  fetchMock.mockImplementation(async (url: string, options?: { method?: string }) => {
    const full = String(url)
    const method = (options?.method ?? 'GET').toUpperCase()

    if (full.includes(OVERRIDES_URL) && method === 'POST') {
      posted.push(full)
      // Parked: the button stays in its pending state until the test lets go,
      // which is exactly the window a second click used to fit into.
      return new Promise((resolve) => {
        releaseCreate = resolve
      })
    }
    if (full.includes(OVERRIDES_URL)) return { data: [] }
    if (full.includes(HOURS_URL)) return { data: CLINIC_HOURS }
    return { data: null }
  })
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('clinic hours override — one Save, one record', () => {
  it('a second click while the first is in flight does not create a second override', async () => {
    const wrapper = await mountSuspended(ClinicHoursPage)
    await flush()

    // The page loaded, so the override calendar is there to open the modal.
    const calendar = wrapper.findComponent(OverrideCalendar)
    expect(calendar.exists()).toBe(true)
    calendar.vm.$emit('add')
    await flush()

    // The override modal is a UModal, so its content is teleported out of the
    // component's own subtree and has to be queried on the document.
    const save = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="clinic-hours-override-save"]'
    )
    expect(save, 'the override modal should be open with its Save button').toBeTruthy()

    save!.click()
    await flush()
    save!.click()
    save!.click()
    await flush()

    expect(posted).toHaveLength(1)

    releaseCreate?.({ data: { id: 'ovr-new' } })
    await flush()
    await flush()

    expect(posted).toHaveLength(1)
  })
})
