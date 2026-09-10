import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `case_intelligence` module.
 *
 * The card embeds this module's clinical-intelligence surface into the
 * patient Summary workflow (`patient.summary.cards`), gated by the
 * module's read permission. The host page never imports this module.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'case_intelligence.patient.summary.cards',
    component: defineAsyncComponent(
      () => import('../components/CaseIntelligenceCard.vue')
    ),
    order: 70,
    permission: 'case_intelligence.read'
  })
})
