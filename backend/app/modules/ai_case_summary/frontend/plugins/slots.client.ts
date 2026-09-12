import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `ai_case_summary` module.
 *
 * The card embeds this module's clinical-intelligence surface into the
 * patient Summary workflow (`patient.summary.cards`), gated by the
 * module's read permission. The host page never imports this module.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'ai_case_summary.patient.summary.cards',
    component: defineAsyncComponent(
      () => import('../components/AICaseSummaryCard.vue')
    ),
    order: 71,
    permission: 'ai_case_summary.read'
  })
})
