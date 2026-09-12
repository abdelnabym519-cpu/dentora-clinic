import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import CopyableField from '../../module_layers/patients/frontend/components/patient/info/CopyableField.vue'
import SetRecallFromTreatmentButton from '../../module_layers/recalls/frontend/components/SetRecallFromTreatmentButton.vue'

/**
 * Clicks that used to go nowhere.
 *
 * Both of these caught their failure and said nothing, which is the worst shape
 * of broken button: it looks healthy, it is clickable, and the only feedback is
 * the absence of feedback. A copy that fails silently means the user pastes
 * something stale somewhere else; "set recall" that fails silently means the
 * clinician clicks, nothing opens, and they assume the recall was set.
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

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

const originalClipboard = Object.getOwnPropertyDescriptor(Navigator.prototype, 'clipboard')

function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

beforeEach(() => {
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']
  fetchMock.mockReset()
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
  if (originalClipboard) {
    Object.defineProperty(Navigator.prototype, 'clipboard', originalClipboard)
  }
})

describe('copy buttons', () => {
  const props = {
    icon: 'i-lucide-phone',
    label: 'Phone',
    value: '+20 100 000 0000',
    copyAriaLabel: 'copy-phone'
  }

  it('reports the failure when the clipboard refuses, instead of doing nothing', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard denied'))
    stubClipboard(writeText)

    const wrapper = await mountSuspended(CopyableField, { props })
    await wrapper.find('[aria-label="copy-phone"]').trigger('click')
    await flush()

    expect(writeText).toHaveBeenCalledWith('+20 100 000 0000')
    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0]?.[0]).toMatchObject({ color: 'error' })
  })

  it('still reports success — and only success — when the copy works', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard(writeText)

    const wrapper = await mountSuspended(CopyableField, { props })
    await wrapper.find('[aria-label="copy-phone"]').trigger('click')
    await flush()

    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0]?.[0]).toMatchObject({ color: 'success' })
  })
})

describe('set-recall button', () => {
  it('reports why it could not open, and opens nothing', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).includes('/api/v1/odontogram/treatments/')) {
        throw failure(404, 'Treatment not found on this host')
      }
      return { data: null }
    })

    const wrapper = await mountSuspended(SetRecallFromTreatmentButton, {
      props: { ctx: { treatmentId: 'tr-1', toothNumber: 11, status: 'completed' } }
    })
    await flush()

    await wrapper.find('button').trigger('click')
    await flush()
    await flush()

    // One report, carrying the server's own reason — a 404 is exactly the
    // status the shared handler stays quiet about, so the click used to be
    // completely silent.
    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0]?.[0]).toMatchObject({ color: 'error' })
    expect(toastSpy.mock.calls[0]?.[0]?.description).toContain('Treatment not found on this host')

    // And the recall modal did not open on a lookup that failed.
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
    expect(wrapper.findAll('form')).toHaveLength(0)
  })
})
