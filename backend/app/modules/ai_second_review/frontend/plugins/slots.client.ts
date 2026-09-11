import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `ai_second_review` module.
 *
 * The card embeds this module's clinical-intelligence surface into the
 * patient Summary workflow (`patient.summary.cards`), gated by the
 * module's read permission. The host page never imports this module.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'ai_second_review.patient.summary.cards',
    component: defineAsyncComponent(
      () => import('../components/AISecondReviewCard.vue')
    ),
    order: 75,
    permission: 'ai_second_review.read'
  })
})
