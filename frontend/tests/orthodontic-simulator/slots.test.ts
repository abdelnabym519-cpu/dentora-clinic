import { beforeEach, describe, expect, it } from 'vitest'

describe('orthodontic_simulator slot registration', () => {
  beforeEach(async () => {
    const { clearSlots } = await import('~/composables/useModuleSlots')
    clearSlots()
  })

  async function runPlugin(): Promise<void> {
    ;(globalThis as Record<string, unknown>).defineNuxtPlugin ??= (fn: unknown) => fn
    const mod = await import('../../module_layers/orthodontic_simulator/frontend/plugins/slots.client')
    const plugin = mod.default as unknown as (ctx: unknown) => unknown
    plugin({ provide: () => {} })
  }

  it('registers one independently removable patient-summary card', async () => {
    await runPlugin()
    const { resolveSlot } = await import('~/composables/useModuleSlots')
    const entries = resolveSlot('patient.summary.cards', {}, { can: () => true })
    const entry = entries.find(e => e.id === 'orthodontic_simulator.patient.summary.cards.simulator')
    expect(entry).toBeDefined()
    expect(entry!.component).toBeDefined()
  })

  it('is permission-gated and ordered after Dental3D cards', async () => {
    await runPlugin()
    const { registerSlot, resolveSlot } = await import('~/composables/useModuleSlots')
    const { defineComponent, h } = await import('vue')

    registerSlot('patient.summary.cards', {
      id: 'dental_3d.patient.summary.cards.viewer',
      component: defineComponent({ render: () => h('span') }),
      order: 50
    })

    const allowed = resolveSlot('patient.summary.cards', {}, { can: () => true })
    const ids = allowed.map(entry => entry.id)
    expect(ids.indexOf('dental_3d.patient.summary.cards.viewer')).toBeLessThan(
      ids.indexOf('orthodontic_simulator.patient.summary.cards.simulator')
    )

    const denied = resolveSlot('patient.summary.cards', {}, { can: () => false })
    expect(denied.find(e => e.id === 'orthodontic_simulator.patient.summary.cards.simulator')).toBeUndefined()
  })
})
