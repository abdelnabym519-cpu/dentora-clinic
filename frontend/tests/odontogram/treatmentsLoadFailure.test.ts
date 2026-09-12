import { defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useTreatments } from '../../module_layers/odontogram/frontend/composables/useTreatments'

/**
 * The odontogram's treatment read.
 *
 * `fetchTreatments` caught every failure and only logged it, so:
 *
 * - a denied or missing read rendered as a **clean mouth** — "this patient has
 *   had nothing done", a clinical claim nobody established, on the screen a
 *   dentist reads before deciding what to do next;
 * - the list was not cleared on failure, so switching from patient A to patient
 *   B with B's read failing left **A's treatments painted under B's name**.
 *
 * The chart's own alert ("never fall through to a fabricated healthy mouth")
 * only watched the tooth-grid read; it now watches this one too.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const TREATMENTS_URL = '/treatments'

/** Patient ids whose read must fail, and with which status. */
let failFor: Record<string, number> = {}

function failure(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), { statusCode: status, status, data: { detail } })
}

function treatmentsFor(patientId: string) {
  return {
    data: [
      { id: `tr-${patientId}-1`, status: 'planned', teeth: [{ tooth_number: 11 }] },
      { id: `tr-${patientId}-2`, status: 'completed', teeth: [{ tooth_number: 21 }] }
    ]
  }
}

let treatmentsApi!: ReturnType<typeof useTreatments>
const Host = defineComponent({
  setup() {
    treatmentsApi = useTreatments()
    return () => h('div')
  }
})

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  failFor = {}
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']

  fetchMock.mockImplementation(async (url: string) => {
    const full = String(url)
    if (full.includes(TREATMENTS_URL)) {
      const patientId = full.split('/patients/')[1]?.split('/')[0] ?? ''
      const status = failFor[patientId]
      if (status) throw failure(status, `Permission denied: odontogram.treatments.read (${patientId})`)
      return treatmentsFor(patientId)
    }
    return { data: null }
  })
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

async function mountHost() {
  const wrapper = await mountSuspended(Host)
  await flush()
  return wrapper
}

describe('odontogram treatments — a failed read is a reported failure', () => {
  it('reports the reason instead of leaving an empty, healthy-looking list', async () => {
    failFor = { 'pat-1': 404 }
    await mountHost()

    await treatmentsApi.fetchTreatments('pat-1')
    await flush()

    expect(treatmentsApi.treatments.value).toEqual([])
    expect(treatmentsApi.error.value).toBeTruthy()
    expect(treatmentsApi.error.value).toContain('pat-1')
    expect(treatmentsApi.loading.value).toBe(false)
  })

  it('does not leave the previous patient\'s treatments on screen when the next read fails', async () => {
    await mountHost()

    await treatmentsApi.fetchTreatments('pat-1')
    await flush()
    expect(treatmentsApi.treatments.value).toHaveLength(2)
    expect(treatmentsApi.error.value).toBeNull()

    // Now switch patient and have that read denied.
    failFor = { 'pat-2': 403 }
    await treatmentsApi.fetchTreatments('pat-2')
    await flush()

    expect(treatmentsApi.treatments.value).toEqual([])
    expect(treatmentsApi.treatments.value.some(t => t.id.includes('pat-1'))).toBe(false)
    expect(treatmentsApi.error.value).toContain('odontogram.treatments.read')
  })

  it('clears the failure once a retry succeeds', async () => {
    failFor = { 'pat-1': 500 }
    await mountHost()

    await treatmentsApi.fetchTreatments('pat-1')
    await flush()
    expect(treatmentsApi.error.value).toBeTruthy()

    failFor = {}
    await treatmentsApi.fetchTreatments('pat-1')
    await flush()

    expect(treatmentsApi.error.value).toBeNull()
    expect(treatmentsApi.treatments.value).toHaveLength(2)
  })

  it('reset() clears the failure as well as the list', async () => {
    failFor = { 'pat-1': 404 }
    await mountHost()

    await treatmentsApi.fetchTreatments('pat-1')
    await flush()
    expect(treatmentsApi.error.value).toBeTruthy()

    treatmentsApi.reset()
    await flush()

    expect(treatmentsApi.error.value).toBeNull()
    expect(treatmentsApi.treatments.value).toEqual([])
  })
})
