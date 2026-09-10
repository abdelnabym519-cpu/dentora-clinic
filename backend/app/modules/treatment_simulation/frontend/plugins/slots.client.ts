import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `treatment_simulation` module.
 *
 * The card embeds this module's clinical-intelligence surface into the
 * patient Summary workflow (`patient.summary.cards`), gated by the
 * module's read permission. The host page never imports this module.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'treatment_simulation.patient.summary.cards',
    component: defineAsyncComponent(
      () => import('../components/TreatmentSimulationCard.vue')
    ),
    order: 74,
    permission: 'treatment_simulation.read'
  })
})
