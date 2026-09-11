import { h, defineComponent, nextTick, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { PERMISSIONS } from '~/config/permissions'
import { useVerifactu } from '../../module_layers/verifactu/frontend/composables/useVerifactu'

/**
 * Veri*Factu isolation.
 *
 * Reported symptom: "Permission denied: verifactu.settings.read" /
 * "Access denied" popped up while navigating ordinary screens (patients,
 * clinical tabs), sometimes followed by the page opening normally.
 *
 * Cause: the compliance banner is registered into the layout-wide
 * ``app.banners`` slot, so it mounted on every screen and polled
 * ``GET /verifactu/health`` for any role holding *any* Veri*Factu grant —
 * while that endpoint requires ``verifactu.settings.read``. Dentists and
 * receptionists hold ``verifactu.records.read`` (see the module manifest),
 * so every poll answered 403 and the shared handler broadcast it.
 *
 * These tests pin the isolation contract in both directions: the ambient
 * probe must stay invisible to unrelated screens, and an explicit
 * Veri*Factu action must still report a genuine denial.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const DENTIST_GRANTS = [
  'patients.read',
  'patients.write',
  'dental_3d.*',
  // What the verifactu manifest actually grants a dentist:
  PERMISSIONS.verifactu.recordsRead
]
const ADMIN_GRANTS = ['*', PERMISSIONS.verifactu.settingsRead, PERMISSIONS.verifactu.queueManage]

function denied(permission: string) {
  return Object.assign(new Error(`Permission denied: ${permission}`), {
    statusCode: 403,
    status: 403,
    data: { detail: `Permission denied: ${permission}` }
  })
}

function healthPayload(rejectedCount: number) {
  return {
    data: {
      enabled: true,
      environment: 'test',
      has_certificate: true,
      certificate_valid_until: null,
      last_aeat_response_at: null,
      next_send_after: null,
      pending_count: 0,
      rejected_count: rejectedCount
    }
  }
}

/** Set the grant list the whole app reads (``useAuth`` → ``usePermissions``). */
async function withGrants(grants: string[]): Promise<void> {
  const { useState } = await import('#app')
  useState<string[]>('auth:permissions', () => []).value = grants
  useState<string[]>('auth:clinics', () => []).value = []
  await nextTick()
}

async function mountBanner() {
  const Banner = (
    await import('../../module_layers/verifactu/frontend/components/verifactu/RejectedGlobalBanner.vue')
  ).default
  return await mountSuspended(Banner)
}

/** Run the verifactu layer plugin exactly like Nuxt does at boot. */
async function runVerifactuSlotsPlugin(): Promise<void> {
  const { clearSlots } = await import('~/composables/useModuleSlots')
  clearSlots()
  ;(globalThis as Record<string, unknown>).defineNuxtPlugin ??= (fn: unknown) => fn
  const mod = await import('../../module_layers/verifactu/frontend/plugins/slots.client')
  const plugin = mod.default as unknown as (ctx: unknown) => unknown
  plugin({ provide: () => {} })
}

/** ``useVerifactu`` needs a component setup context (i18n + toast). */
async function withVerifactu(): Promise<ReturnType<typeof useVerifactu>> {
  let verifactu!: ReturnType<typeof useVerifactu>
  const Passthrough: Component = defineComponent({
    setup() {
      verifactu = useVerifactu()
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return verifactu
}

beforeEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('slot registration — the banner is gated on the grant the endpoint needs', () => {
  it('declares verifactu.settings.read, so the layout never mounts it for a dentist', async () => {
    await runVerifactuSlotsPlugin()
    const { resolveSlot } = await import('~/composables/useModuleSlots')
    const { isGranted } = await import('~/utils/permissions')

    const dentistCan = (p: string) => isGranted(p, DENTIST_GRANTS)
    const adminCan = (p: string) => isGranted(p, ADMIN_GRANTS)

    const entries = resolveSlot('app.banners', {}, { can: () => true })
    const banner = entries.find(e => e.id === 'verifactu.app.banners.rejected')
    expect(banner).toBeDefined()
    expect(banner?.permission).toBe(PERMISSIONS.verifactu.settingsRead)

    // The reported bug: a dentist holds records.read, the probe needs
    // settings.read — the banner must not mount at all.
    expect(resolveSlot('app.banners', {}, { can: dentistCan })).toHaveLength(0)
    expect(resolveSlot('app.banners', {}, { can: adminCan })).toHaveLength(1)
  })

  it('gates the invoice compliance panel on the records grant it reads', async () => {
    await runVerifactuSlotsPlugin()
    const { resolveSlot } = await import('~/composables/useModuleSlots')
    const { isGranted } = await import('~/utils/permissions')

    const ctx = { clinic: { country: 'ES' }, invoice: { compliance_data: { ES: { state: 'rejected' } } } }
    const entries = resolveSlot('invoice.detail.compliance', ctx, {
      can: p => isGranted(p, ['billing.read'])
    })
    expect(entries).toHaveLength(0)

    const withRecords = resolveSlot('invoice.detail.compliance', ctx, {
      can: p => isGranted(p, ['billing.read', PERMISSIONS.verifactu.recordsRead])
    })
    expect(withRecords).toHaveLength(1)
  })
})

describe('ambient probe — a Veri*Factu denial cannot contaminate other screens', () => {
  it('does not even call /verifactu/health for a role without the settings grant', async () => {
    await withGrants(DENTIST_GRANTS)
    fetchMock.mockImplementation(async () => healthPayload(3))

    const wrapper = await mountBanner()

    const healthCalls = fetchMock.mock.calls.filter(call =>
      String(call[0]).includes('/verifactu/health')
    )
    expect(healthCalls).toHaveLength(0)
    expect(toastSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('Verifactu')
    wrapper.unmount()
  })

  it('stays silent and stops polling when an authorized-looking probe is denied', async () => {
    await withGrants([PERMISSIONS.verifactu.settingsRead])
    vi.useFakeTimers({ toFake: ['setInterval'] })
    fetchMock.mockRejectedValue(denied('verifactu.settings.read'))

    const wrapper = await mountBanner()
    await vi.advanceTimersByTimeAsync(180_000)

    const healthCalls = fetchMock.mock.calls.filter(call =>
      String(call[0]).includes('/verifactu/health')
    )
    // One probe, then it gives up: no toast, no banner, no request storm
    // on the screen the user is actually working in.
    expect(healthCalls).toHaveLength(1)
    expect(toastSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toBe('')
    wrapper.unmount()
  })

  it('keeps working for an authorized user — rejected records still raise the banner', async () => {
    await withGrants(ADMIN_GRANTS)
    fetchMock.mockImplementation(async () => healthPayload(2))

    const wrapper = await mountBanner()
    await nextTick()

    expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/verifactu/health'))).toBe(true)
    expect(wrapper.html()).toContain('/settings/verifactu/queue')
    expect(toastSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('explicit Veri*Factu actions still report a genuine denial', () => {
  it('reports the operation and the missing permission when not silenced', async () => {
    await withGrants(DENTIST_GRANTS)
    fetchMock.mockRejectedValue(denied('verifactu.settings.read'))

    const verifactu = await withVerifactu()

    await expect(verifactu.health()).rejects.toMatchObject({ statusCode: 403 })

    expect(toastSpy).toHaveBeenCalledTimes(1)
    const description = String(toastSpy.mock.calls[0]?.[0]?.description ?? '')
    expect(description).toContain('Verifactu')
    expect(description).toContain('verifactu.settings.read')
  })

  it('hands the same denial to the caller untouched when silenced', async () => {
    await withGrants(DENTIST_GRANTS)
    fetchMock.mockRejectedValue(denied('verifactu.settings.read'))

    const verifactu = await withVerifactu()

    const error = await verifactu.health({ silent: true }).catch((e: unknown) => e)
    expect(error).toMatchObject({ statusCode: 403 })
    expect((error as { data: { detail: string } }).data.detail)
      .toBe('Permission denied: verifactu.settings.read')
    expect(toastSpy).not.toHaveBeenCalled()
  })
})
