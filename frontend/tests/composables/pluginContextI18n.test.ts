import { getCurrentInstance } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import { useGlobalT } from '~/utils/i18nScope'
import settingsRegistryPlugin from '~/plugins/settings.registry'

/**
 * Composables that a Nuxt *plugin* acquires must not depend on a component
 * instance.
 *
 * `app/plugins/settings.registry.ts` calls `useClinic()` -> `useApi()` while
 * the app is still booting. Both used to take translations from vue-i18n's
 * `useI18n()`, which resolves the current component instance and throws
 * `Must be called at the top of a 'setup' function` when there is none. On SSR
 * that aborted the whole render — every page came back 500, and the browser
 * only ever saw the downstream symptoms ("Failed to fetch clinic",
 * "useModules: backend fetch failed", "Patients connection error").
 *
 * These tests run the real composables and the real plugin in a Nuxt context
 * with no component instance, which is precisely the plugin's situation.
 */

const { toastSpy, fetchMock } = vi.hoisted(() => ({ toastSpy: vi.fn(), fetchMock: vi.fn() }))

mockNuxtImport('useToast', () => () => ({ add: toastSpy }))
mockNuxtImport('$fetch', () => fetchMock)

/** ofetch-shaped failure: status + parsed body under `.data`. */
function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(typeof detail === 'string' ? detail : 'request failed'), {
    statusCode: status,
    status,
    data: { detail }
  })
}

describe('plugin-context i18n scope', () => {
  afterEach(() => {
    vi.clearAllMocks()
    _resetApiErrorNotifications()
  })

  it('has no component instance, so it reproduces the plugin context', () => {
    // Guard for the whole suite: if this ever becomes non-null the tests below
    // would pass for the wrong reason.
    expect(getCurrentInstance()).toBeNull()
  })

  it('resolves real translations through the Nuxt app scope', () => {
    const t = useGlobalT()
    const translated = t('common.error')

    expect(typeof translated).toBe('string')
    expect(translated.length).toBeGreaterThan(0)
    // An unresolved key would come back verbatim.
    expect(translated).not.toBe('common.error')
  })

  it('acquires useApi() outside setup', async () => {
    const { useApi } = await import('~/composables/useApi')

    expect(() => useApi()).not.toThrow()
    const api = useApi()
    expect(typeof api.get).toBe('function')
    expect(typeof api.post).toBe('function')
  })

  it('acquires useClinic() outside setup — the plugin\'s own entry point', async () => {
    const { useClinic } = await import('~/composables/useClinic')

    expect(() => useClinic()).not.toThrow()
    expect(typeof useClinic().fetchClinic).toBe('function')
  })

  it('runs the settings.registry plugin factory to completion', async () => {
    const nuxtApp = useNuxtApp()
    const run = settingsRegistryPlugin as unknown as (app: unknown) => unknown

    // This is the exact call that 500'd every SSR render.
    let failure: unknown
    try {
      await run(nuxtApp)
    } catch (error) {
      failure = error
    }

    expect(failure).toBeUndefined()
  })

  it('still surfaces translated API errors from that context', async () => {
    fetchMock.mockRejectedValueOnce(httpError(403, 'not allowed'))

    const { useApi } = await import('~/composables/useApi')
    const t = useGlobalT()

    await expect(useApi().get('/api/v1/denied')).rejects.toThrow()

    expect(toastSpy).toHaveBeenCalledTimes(1)
    const notification = toastSpy.mock.calls[0][0] as { title: string, color: string }
    expect(notification.title).toBe(t('common.forbidden'))
    expect(notification.title).not.toBe('common.forbidden')
    expect(notification.color).toBe('error')
  })
})
