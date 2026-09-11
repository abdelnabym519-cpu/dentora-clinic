import { h, defineComponent, nextTick, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useHomeAgenda } from '../../module_layers/agenda/frontend/composables/useHomeAgenda'

/**
 * Home-dashboard agenda widgets (today KPI, "in clinic now", timeline
 * strip, unconfirmed panel) are *ambient*: they mount for every user who
 * holds ``agenda.appointments.read``, they re-fetch on keep-alive
 * re-entry, and the "in clinic" tile re-polls every 60 s.
 *
 * Two failure modes are pinned here:
 *
 * 1. A failed ambient load must not raise a global toast. The widgets
 *    render inside whatever screen the user opened the dashboard from,
 *    and a poll that fails every minute would stack one toast per tick
 *    for a failure the user did not cause and cannot act on.
 * 2. A failed load must not be flattened into an *empty* load. "No one
 *    in clinic" and "we could not load" are different statements; the
 *    tiles expose ``todayError`` / ``tomorrowError`` and render an
 *    explicit error state with a retry instead of a false all-clear.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const APPOINTMENTS_URL = '/api/v1/agenda/appointments'

function appointment(id: string, status: string) {
  const now = new Date()
  const iso = now.toISOString()
  return {
    id,
    clinic_id: 'clinic-1',
    patient_id: 'patient-1',
    professional_id: 'pro-1',
    start_time: iso,
    end_time: iso,
    status,
    cabinet: null,
    treatment_type: null,
    notes: null,
    confirmation_sent_at: null,
    confirmed_at: null,
    checked_in_at: null,
    completed_at: null,
    cancelled_at: null,
    cancellation_reason: null,
    patient: null,
    professional: null,
    created_at: iso,
    updated_at: iso
  }
}

function failure(status: number, detail: string) {
  return Object.assign(new Error(detail), {
    statusCode: status,
    status,
    data: { detail }
  })
}

/**
 * Fail *only* the widget's own request. The mock is shared with app boot
 * traffic (auth init, module nav), which must keep answering so the
 * component under test can mount.
 */
function failAppointments(status: number, detail: string): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes(APPOINTMENTS_URL)) throw failure(status, detail)
    return { data: null }
  })
}

/** Let the widget's async ``onMounted`` load settle. */
async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

/** ``useHomeAgenda`` keeps its state in ``useState`` — reset between cases. */
async function resetHomeAgendaState(): Promise<void> {
  const { useState } = await import('#app')
  useState<unknown[]>('agenda.home:today', () => []).value = []
  useState<unknown[]>('agenda.home:tomorrow-unconfirmed', () => []).value = []
  useState<boolean>('agenda.home:today-loaded', () => false).value = false
  useState<boolean>('agenda.home:tomorrow-loaded', () => false).value = false
  useState<boolean>('agenda.home:today-error', () => false).value = false
  useState<boolean>('agenda.home:tomorrow-error', () => false).value = false
  await nextTick()
}

/** The composable needs a component setup context (useApi → i18n/toast). */
async function withHomeAgenda(): Promise<ReturnType<typeof useHomeAgenda>> {
  let agenda!: ReturnType<typeof useHomeAgenda>
  const Passthrough: Component = defineComponent({
    setup() {
      agenda = useHomeAgenda()
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return agenda
}

/** Only the widget's own requests — app boot traffic shares the mock. */
function appointmentCalls() {
  return fetchMock.mock.calls.filter(call => String(call[0]).includes(APPOINTMENTS_URL))
}

beforeEach(async () => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  await resetHomeAgendaState()
})

describe('useHomeAgenda — ambient loads never broadcast a global error', () => {
  it('reports a 403 through the error flag only (no toast)', async () => {
    failAppointments(403, 'Permission denied: agenda.appointments.read')

    const agenda = await withHomeAgenda()
    const result = await agenda.fetchToday()

    expect(result).toEqual([])
    expect(agenda.todayError.value).toBe(true)
    expect(agenda.todayLoaded.value).toBe(true)
    expect(toastSpy).not.toHaveBeenCalled()
    expect(appointmentCalls().length).toBeGreaterThan(0)
  })

  it('reports a 500 through the error flag only (no toast)', async () => {
    failAppointments(503, 'Service unavailable')

    const agenda = await withHomeAgenda()
    await agenda.fetchToday()

    expect(agenda.todayError.value).toBe(true)
    expect(agenda.todayAppointments.value).toEqual([])
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('does not turn a failed tomorrow load into "all confirmed"', async () => {
    failAppointments(500, 'Boom')

    const agenda = await withHomeAgenda()
    const result = await agenda.fetchTomorrowUnconfirmed()

    expect(result).toEqual([])
    expect(agenda.tomorrowError.value).toBe(true)
    expect(agenda.tomorrowLoaded.value).toBe(true)
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('clears the error flag once a retry succeeds', async () => {
    failAppointments(500, 'Boom')

    const agenda = await withHomeAgenda()
    await agenda.fetchToday()
    expect(agenda.todayError.value).toBe(true)

    fetchMock.mockImplementation(async () => ({ data: [appointment('a1', 'checked_in')] }))
    const recovered = await agenda.fetchToday()

    expect(recovered).toHaveLength(1)
    expect(agenda.todayError.value).toBe(false)
    expect(agenda.todayAppointments.value.map(a => a.id)).toEqual(['a1'])
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('keeps a successful load error-free', async () => {
    fetchMock.mockResolvedValue({
      data: [appointment('a1', 'in_treatment'), appointment('a2', 'scheduled')]
    })

    const agenda = await withHomeAgenda()
    const result = await agenda.fetchToday()

    expect(result).toHaveLength(2)
    expect(agenda.todayError.value).toBe(false)
    expect(agenda.todayLoaded.value).toBe(true)
  })
})

describe('InClinicNowTile — a failed poll renders an error state, not a false all-clear', () => {
  async function mountTile() {
    const Tile = (
      await import('../../module_layers/agenda/frontend/components/home/InClinicNowTile.vue')
    ).default
    return await mountSuspended(Tile)
  }

  it('shows the error state with a retry when the load fails', async () => {
    failAppointments(500, 'Boom')

    const wrapper = await mountTile()
    await flush()

    expect(wrapper.find('[data-testid="in-clinic-error"]').exists()).toBe(true)
    // The misleading all-clear must not be rendered alongside it, and no
    // count may be shown for data that never arrived.
    expect(wrapper.find('[data-testid="in-clinic-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="in-clinic-total"]').exists()).toBe(false)
    expect(toastSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows the real count when the load succeeds', async () => {
    fetchMock.mockImplementation(async () => ({
      data: [appointment('a1', 'in_treatment'), appointment('a2', 'checked_in')]
    }))

    const wrapper = await mountTile()
    await flush()

    expect(wrapper.find('[data-testid="in-clinic-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="in-clinic-total"]').text()).toBe('2')
    expect(wrapper.find('[data-testid="in-clinic-empty"]').exists()).toBe(false)
    expect(toastSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('still renders the genuine all-clear when the load succeeds with no rows', async () => {
    fetchMock.mockImplementation(async () => ({ data: [] }))

    const wrapper = await mountTile()
    await flush()

    expect(wrapper.find('[data-testid="in-clinic-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="in-clinic-total"]').text()).toBe('0')
    expect(wrapper.find('[data-testid="in-clinic-empty"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
