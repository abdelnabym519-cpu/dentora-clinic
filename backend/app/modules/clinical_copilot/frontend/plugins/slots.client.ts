import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `clinical_copilot` module.
 *
 * The card embeds this module's clinical-intelligence surface into the
 * patient Summary workflow (`patient.summary.cards`), gated by the
 * module's read permission. The host page never imports this module.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'clinical_copilot.patient.summary.cards',
    component: defineAsyncComponent(
      () => import('../components/ClinicalCopilotCard.vue')
    ),
    order: 76,
    permission: 'clinical_copilot.read'
  })
})
