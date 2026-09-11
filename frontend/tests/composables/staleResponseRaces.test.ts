import { h, defineComponent, nextTick, ref, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useTreatmentCatalogSearch } from '~/composables/useTreatmentCatalogSearch'
import { usePatientTimeline } from '../../module_layers/patient_timeline/frontend/composables/usePatientTimeline'
import { usePublicBooking } from '../../module_layers/booking/frontend/composables/usePublicBooking'
import PatientClinicalNotesByPlan from '../../module_layers/clinical_notes/frontend/components/PatientClinicalNotesByPlan.vue'

/**
 * A fetch triggered by something the user can change faster than the network
 * answers — the selected patient, the day, the search box — has to drop its
 * result once a newer fetch for the same slot has started. These tests answer
 * the requests in the *worst* order (the stale one last) and assert that what
 * ends up on screen belongs to the state the user is actually in.
 */

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))

mockNuxtImport('$fetch', () => fetchMock)

interface Queued {
  url: string
  resolve: (payload: unknown) => void
}

let queue: Queued[] = []

/** Every request matching `fragment` is parked until the test resolves it. */
function parkRequests(fragment: string): void {
  fetchMock.mockImplementation((url: string) => {
    const full = String(url)
    if (full.includes(fragment)) {
      return new Promise((resolve) => {
        queue.push({ url: full, resolve })
      })
    }
    return Promise.resolve({ data: null })
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

beforeEach(() => {
  queue = []
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']
})

afterEach(() => {
  fetchMock.mockReset()
  _resetApiErrorNotifications()
})

describe('stale responses — the newest request owns the screen', () => {
  it('the patient timeline shows the patient it is on, not the one it left', async () => {
    parkRequests('/api/v1/patient_timeline/patients/')

    const patientId = ref<string | undefined>('pat-a')
    const timeline = await inSetup(() => usePatientTimeline(patientId))
    await flush()

    patientId.value = 'pat-b'
    await flush()

    expect(queue.map(q => q.url.includes('pat-b'))).toEqual([false, true])

    // The newer patient answers first, the stale one last.
    queue[1]!.resolve({
      data: { entries: [{ id: 'entry-b', event_type: 'visit' }], total: 1, has_more: false }
    })
    await flush()
    queue[0]!.resolve({
      data: { entries: [{ id: 'entry-a', event_type: 'visit' }], total: 1, has_more: false }
    })
    await flush()

    expect(timeline.entries.value.map(e => e.id)).toEqual(['entry-b'])
  })

  it('public booking shows the slots of the day the visitor selected', async () => {
    parkRequests('/slots')

    const booking = await inSetup(() => usePublicBooking('clinic-slug'))

    const monday = booking.fetchSlots('prof-1', '2026-09-14')
    const tuesday = booking.fetchSlots('prof-1', '2026-09-15')
    await flush()

    expect(queue).toHaveLength(2)

    queue[1]!.resolve({ data: [{ id: 'slot-tue-0900', start_time: '09:00' }] })
    await flush()
    queue[0]!.resolve({ data: [{ id: 'slot-mon-1700', start_time: '17:00' }] })
    await flush()
    await Promise.all([monday, tuesday])

    // A visitor clicking through days must never be offered — and book into —
    // the previous day's slots.
    expect(booking.slots.value.map(s => s.id)).toEqual(['slot-tue-0900'])
  })

  it('a treatment search lists what matches the text in the box', async () => {
    parkRequests('/api/v1/catalog/items')

    const search = await inSetup(() => useTreatmentCatalogSearch())

    const first = search.search('endodon')
    const second = search.search('endodoncia molar')
    await flush()

    expect(queue.length).toBeGreaterThanOrEqual(2)
    const stale = queue[0]!
    const newest = queue[queue.length - 1]!

    newest.resolve({ data: [{ id: 'item-molar', name: 'Root canal — molar' }] })
    await flush()
    stale.resolve({ data: [{ id: 'item-generic', name: 'Root canal' }] })
    await flush()
    await Promise.all([first, second])

    expect(search.searchResults.value.map(i => i.id)).toEqual(['item-molar'])
    expect(search.isSearching.value).toBe(false)
  })

  it('the patient notes tab renders the notes of the patient it is on', async () => {
    parkRequests('/api/v1/clinical_notes/patients/')

    const group = (planNumber: string, title: string) => ({
      plan: { id: `plan-${planNumber}`, plan_number: planNumber, title, status: 'in_progress' },
      plan_notes: [{
        id: `note-${planNumber}`,
        body: `Note body ${planNumber}`,
        created_at: '2026-09-01T10:00:00Z',
        source: 'plan'
      }],
      treatments: []
    })

    const wrapper = await mountSuspended(PatientClinicalNotesByPlan, {
      props: { ctx: { patientId: 'pat-a' } }
    })
    await flush()

    await wrapper.setProps({ ctx: { patientId: 'pat-b' } })
    await flush()

    expect(queue.map(q => q.url.includes('pat-b'))).toEqual([false, true])

    queue[1]!.resolve({ data: [group('PLAN-B', ' Bruxism splint')] })
    await flush()
    queue[0]!.resolve({ data: [group('PLAN-A', 'Upper wisdom tooth')] })
    await flush()

    const text = wrapper.text()
    expect(text).toContain('PLAN-B')
    expect(text).not.toContain('PLAN-A')
  })
})
