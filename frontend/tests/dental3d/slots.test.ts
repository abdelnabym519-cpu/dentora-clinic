import { beforeEach, describe, expect, it } from 'vitest'

/**
 * Slot-registry integration for the dental_3d layer: the plugin file
 * must register its card into the canonical `patient.summary.cards`
 * slot, gated on `dental_3d.read`, exactly like the odontogram's
 * DiagnosesCard. The registry is the only host↔module contract — if
 * this breaks, the module silently disappears from the patient UI.
 */

describe('dental_3d slot registration', () => {
  beforeEach(async () => {
    const { clearSlots } = await import('~/composables/useModuleSlots')
    clearSlots()
  })

  async function runPlugin(): Promise<void> {
    // The layer plugin relies on Nuxt's `defineNuxtPlugin` auto-import.
    // The vitest nuxt environment provides it; the passthrough stub
    // keeps the test deterministic if it does not. Importing the module
    // only *defines* the plugin — like Nuxt at boot, we must invoke
    // it to run the registration body.
    ;(globalThis as Record<string, unknown>).defineNuxtPlugin ??= (fn: unknown) => fn
    const mod = await import('../../module_layers/dental_3d/frontend/plugins/slots.client')
    const plugin = mod.default as unknown as (ctx: unknown) => unknown
    plugin({ provide: () => {} })
  }

  it('registers the viewer card in patient.summary.cards', async () => {
    await runPlugin()
    const { resolveSlot } = await import('~/composables/useModuleSlots')

    const entries = resolveSlot('patient.summary.cards', {}, { can: () => true })
    const entry = entries.find(e => e.id === 'dental_3d.patient.summary.cards.viewer')
    expect(entry).toBeDefined()
    expect(entry!.component).toBeDefined()
  })

  it('gates the card on the dental_3d.read permission', async () => {
    await runPlugin()
    const { resolveSlot } = await import('~/composables/useModuleSlots')

    const entries = resolveSlot('patient.summary.cards', {}, { can: () => false })
    expect(entries.find(e => e.id === 'dental_3d.patient.summary.cards.viewer')).toBeUndefined()
  })

  it('orders the card after the odontogram diagnoses card (order 50)', async () => {
    await runPlugin()
    const { registerSlot, resolveSlot } = await import('~/composables/useModuleSlots')
    const { defineComponent, h } = await import('vue')

    registerSlot('patient.summary.cards', {
      id: 'odontogram.patient.summary.cards.diagnoses',
      component: defineComponent({ render: () => h('span') }),
      order: 40
    })

    const entries = resolveSlot('patient.summary.cards', {}, { can: () => true })
    const ids = entries.map(e => e.id)
    expect(ids.indexOf('odontogram.patient.summary.cards.diagnoses')).toBeLessThan(
      ids.indexOf('dental_3d.patient.summary.cards.viewer')
    )
  })
})
