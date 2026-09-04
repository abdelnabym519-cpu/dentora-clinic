import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `orthodontic_planning` module.
 *
 * The host (`patients` summary grid) exposes stable slot names and
 * never imports this module — the registry is the only contract.
 */
export default defineNuxtPlugin(() => {
  // Patient Resumen — orthodontic planning status card.
  registerSlot('patient.summary.cards', {
    id: 'orthodontic_planning.patient.summary.cards.planning',
    component: defineAsyncComponent(
      () => import('../components/OrthodonticPlanningCard.vue')
    ),
    order: 70,
    permission: 'orthodontic_planning.read'
  })
})
