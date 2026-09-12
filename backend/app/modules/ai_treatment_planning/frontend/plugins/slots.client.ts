import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `ai_treatment_planning` module.
 *
 * The card embeds this module's clinical-intelligence surface into the
 * patient Summary workflow (`patient.summary.cards`), gated by the
 * module's read permission. The host page never imports this module.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'ai_treatment_planning.patient.summary.cards',
    component: defineAsyncComponent(
      () => import('../components/AITreatmentPlanningCard.vue')
    ),
    order: 73,
    permission: 'ai_treatment_planning.read'
  })
})
