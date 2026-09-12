import { defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useNotificationSettings } from '../../module_layers/notifications/frontend/composables/useNotificationSettings'

/**
 * The notification-settings writes.
 *
 * Every button on that page carries `:loading`, which blocks a second *mouse*
 * click — but the two forms are also reachable through implicit submission
 * (Enter in a field), and any handler can be re-entered in the same tick before
 * Vue has rendered the disabled state. None of the four operations checked its
 * own busy flag, so a re-entry sent the request again: a second test email to
 * the patient's address, a second SMTP credentials write that can store a
 * half-applied password.
 *
 * The composable is the choke point every consumer goes through, so the guard
 * lives there.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

let calls: Array<{ url: string, method: string }> = []
let release: Array<(value: unknown) => void> = []

// A minimal host so the composable runs inside a real Nuxt/Vue context.
let settingsApi!: ReturnType<typeof useNotificationSettings>
const Host = defineComponent({
  setup() {
    settingsApi = useNotificationSettings()
    return () => h('div')
  }
})

const SETTINGS_PAYLOAD = { settings: { appointment_reminder: { enabled: true } } }
const SMTP_PAYLOAD = { host: 'smtp.example.test', from_email: 'clinic@example.test' }
const SMTP_TEST_PAYLOAD = {
  host: 'smtp.example.test',
  port: 587,
  use_tls: true,
  use_ssl: false,
  from_email: 'clinic@example.test',
  to_email: 'dentist@example.test'
}

/**
 * A guarded re-entry returns immediately. An unguarded one goes to the network
 * and stays parked, so resolve it to `'PARKED'` instead of waiting the test out
 * — that turns "the guard is missing" into a readable assertion failure.
 */
async function callOrParked<T>(promise: Promise<T>): Promise<T | 'PARKED'> {
  return await Promise.race([
    promise,
    new Promise<'PARKED'>(resolve => setTimeout(() => resolve('PARKED'), 300))
  ])
}

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

beforeEach(() => {
  calls = []
  release = []
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']
  // The busy flags live in shared useState keys, so start each test clean.
  for (const key of [
    'notifications:saving',
    'notifications:testing',
    'notifications:smtp:saving',
    'notifications:smtp:testing'
  ]) {
    useState<boolean>(key, () => false).value = false
  }

  fetchMock.mockImplementation((url: string, options?: { method?: string }) => {
    const method = (options?.method ?? 'GET').toUpperCase()
    // Reads (the module's own init, the settings load) answer at once — parking
    // those would stall the mount itself. Only the four writes are held open,
    // which is the window a re-entry fits into.
    if (method === 'GET') return Promise.resolve({ data: null })
    calls.push({ url: String(url), method })
    return new Promise((resolve) => {
      release.push(resolve)
    })
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

describe('notification settings — one press, one request', () => {
  it('saving the settings twice writes once', async () => {
    await mountHost()

    void settingsApi.updateSettings(SETTINGS_PAYLOAD)
    await flush()
    const second = await callOrParked(settingsApi.updateSettings(SETTINGS_PAYLOAD))

    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'PUT' })
    expect(calls[0]?.url).toContain('/api/v1/notifications/settings')
    // The superseded call reports "not done" and adds no toast of its own: the
    // in-flight one owns the single report.
    expect(second).toBe(false)
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('sending a test email twice sends one email', async () => {
    await mountHost()

    void settingsApi.testEmailConnection('dentist@example.test')
    await flush()
    const second = await callOrParked(settingsApi.testEmailConnection('dentist@example.test'))

    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'POST' })
    expect(calls[0]?.url).toContain('/api/v1/notifications/test')
    expect(second).toBe(false)
  })

  it('saving SMTP settings twice writes once', async () => {
    await mountHost()

    void settingsApi.updateSmtpSettings(SMTP_PAYLOAD)
    await flush()
    const second = await callOrParked(settingsApi.updateSmtpSettings(SMTP_PAYLOAD))

    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'PUT' })
    expect(calls[0]?.url).toContain('/api/v1/notifications/smtp-settings')
    expect(second).toBe(false)
  })

  it('testing the SMTP connection twice sends one test', async () => {
    await mountHost()

    void settingsApi.testSmtpConnection(SMTP_TEST_PAYLOAD)
    await flush()
    const second = await callOrParked(settingsApi.testSmtpConnection(SMTP_TEST_PAYLOAD))

    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'POST' })
    expect(calls[0]?.url).toContain('/api/v1/notifications/smtp-settings/test')
    expect(second).toBe(false)
  })

  it('is not wedged: once the first save settles, the next one goes through', async () => {
    await mountHost()

    const first = settingsApi.updateSettings(SETTINGS_PAYLOAD)
    await flush()
    release.shift()?.({ data: SETTINGS_PAYLOAD.settings })
    expect(await first).toBe(true)
    await flush()

    void settingsApi.updateSettings(SETTINGS_PAYLOAD)
    await flush()

    expect(calls).toHaveLength(2)
    // Exactly one report for the one save that completed.
    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0]?.[0]).toMatchObject({ color: 'success' })
  })
})
