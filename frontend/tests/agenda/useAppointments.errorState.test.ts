import { h, defineComponent, nextTick, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useAppointments } from '../../module_layers/agenda/frontend/composables/useAppointments'

/**
 * The agenda board's data load.
 *
 * Two things are pinned here:
 *
 * 1. **Background refreshes are silent.** The kanban re-reads the day every
 *    30 s and again whenever the tab regains focus. Those are not user
 *    actions, so a failing backend must not stack one global toast per tick
 *    on top of whatever the user is doing — the board renders the failure
 *    inline instead.
 * 2. **The inline error is real.** It used to be the hardcoded English
 *    string ``'Failed to fetch appointments'``, which dropped the backend's
 *    reason (the missing permission, the outage) and was never localized.
 *    Explicit loads still announce themselves, naming the operation.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const LIST_URL = '/api/v1/agenda/appointments'

function failure(status: number, detail: string) {
  return Object.assign(new Error(detail), {
    statusCode: status,
    status,
    data: { detail }
  })
}

/** Fail only the board's own request; boot traffic keeps answering. */
function failList(status: number, detail: string): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).includes(LIST_URL)) throw failure(status, detail)
    return { data: [] }
  })
}

async function withAppointments(): Promise<ReturnType<typeof useAppointments>> {
  let appointments!: ReturnType<typeof useAppointments>
  const Passthrough: Component = defineComponent({
    setup() {
      appointments = useAppointments()
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return appointments
}

function dayRange(): [Date, Date] {
  const start = new Date('2026-05-18T00:00:00Z')
  const end = new Date('2026-05-18T23:59:59Z')
  return [start, end]
}

/** The toast payload as text — locale-independent assertions. */
function toastedText(): string {
  return JSON.stringify(toastSpy.mock.calls)
}

beforeEach(async () => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  const { useState } = await import('#app')
  useState<unknown[]>('appointments:list', () => []).value = []
  useState<boolean>('appointments:loading', () => false).value = false
  useState<string | null>('appointments:error', () => null).value = null
  await nextTick()
})

describe('useAppointments.fetchAppointments — error scope', () => {
  it('a silent (background) failure raises no toast but sets an inline error', async () => {
    failList(503, 'Service unavailable')

    const state = await withAppointments()
    const [start, end] = dayRange()
    const result = await state.fetchAppointments(start, end, { silent: true })

    expect(result).toEqual([])
    expect(toastSpy).not.toHaveBeenCalled()
    expect(state.error.value).toContain('Service unavailable')
    // The old hardcoded string carried no reason and no translation.
    expect(state.error.value).not.toBe('Failed to fetch appointments')
    expect(state.isLoading.value).toBe(false)
  })

  it('an explicit failure is announced and names the missing permission', async () => {
    failList(403, 'Permission denied: agenda.appointments.read')

    const state = await withAppointments()
    const [start, end] = dayRange()
    await state.fetchAppointments(start, end)

    expect(toastSpy).toHaveBeenCalled()
    expect(toastedText()).toContain('agenda.appointments.read')
    expect(state.error.value).toContain('agenda.appointments.read')
  })

  it('a network failure falls back to a localized reason, never a bare status', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes(LIST_URL)) throw new TypeError('fetch failed')
      return { data: [] }
    })

    const state = await withAppointments()
    const [start, end] = dayRange()
    await state.fetchAppointments(start, end, { silent: true })

    expect(state.error.value).toBeTruthy()
    expect(state.error.value).not.toBe('Failed to fetch appointments')
    // A raw "fetch failed" is a stack-trace fragment, not a message a
    // patient-facing UI can show: the localized network text must win.
    expect(state.error.value).not.toContain('fetch failed')
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('clears the inline error once a retry succeeds', async () => {
    failList(500, 'Boom')

    const state = await withAppointments()
    const [start, end] = dayRange()
    await state.fetchAppointments(start, end, { silent: true })
    expect(state.error.value).toBeTruthy()

    fetchMock.mockImplementation(async () => ({
      data: [{ id: 'a1', status: 'scheduled', start_time: start.toISOString() }]
    }))
    const recovered = await state.fetchAppointments(start, end)

    expect(recovered).toHaveLength(1)
    expect(state.error.value).toBeNull()
    expect(toastSpy).not.toHaveBeenCalled()
  })
})
